"""Hand-made tower and Breach stronghold rules (from v0.48). atlas_detect uses their towers as a feature for
its tower model and their strongholds directly; everything else of the old landmark module was retired."""

from __future__ import annotations

from dataclasses import dataclass
import functools
import math
import weakref

import cv2
import numpy as np

import rc_paths


@functools.lru_cache(maxsize=None)
def _template(name: str):
    """a tower reference picture from references/, read once"""
    return cv2.imread(str(rc_paths.ref(name)), cv2.IMREAD_COLOR)


_UI: dict = {}


def game_ui_mask(image: np.ndarray) -> np.ndarray:
    """255 = atlas, 0 = game interface (computed once per screenshot; read-only)"""
    hit = _UI.get(id(image))
    if hit is not None and hit[0]() is image:
        return hit[1]
    m = _game_ui_mask_calc(image)
    m.flags.writeable = False
    _UI.clear()
    _UI[id(image)] = (weakref.ref(image), m)
    return m


def _game_ui_mask_calc(image: np.ndarray) -> np.ndarray:
    """255 means inspectable map; 0 means known interface, not atlas terrain.

    Bounds are intentionally restricted to the HUD, Act selector and world
    header. A user can still manually click inside an excluded region.
    """
    h, w = image.shape[:2]
    mask = np.full((h, w), 255, dtype=np.uint8)
    # WORLD heading, act selector, search bar and top-corner controls.
    mask[:min(h, 112), int(w*.22):int(w*.72)] = 0
    mask[:min(h, 94), :min(w, 92)] = 0
    mask[:min(h, 77), max(0, w-200):] = 0
    # The two large Life/Mana globes and the action bar. Unlike dark terrain,
    # these fixed HUD elements are bright blue and repeatedly fooled v0.5.
    # Only the globe *itself* occupies the corner. The old 185x175 right
    # rectangle hid real atlas nodes at the lower-right edge when the Atlas
    # filled a screenshot (notably Screenshot_30).
    mask[max(0, h-100):, :min(w, 100)] = 0
    mask[max(0, h-100):, max(0, w-100):] = 0
    mask[max(0, h-27):, :] = 0

    # Optional vertical side action bars present in full game screenshots.
    # Avoid cropping legitimate right-edge nodes in screenshots without HUD.
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    for side in ("left", "right"):
        x0 = 0 if side == "left" else max(0, w-115)
        x1 = min(w, 115) if side == "left" else w
        strip = gray[min(h, 95):max(96, h-140), x0:x1]
        if strip.shape[0] < 150 or strip.shape[1] < 45:
            continue
        circles = cv2.HoughCircles(cv2.GaussianBlur(strip, (5, 5), 1),
                                  cv2.HOUGH_GRADIENT, dp=1.4, minDist=37,
                                  param1=100, param2=25, minRadius=12, maxRadius=30)
        # Circle count alone is unsafe: map objective badges and even rounded
        # mountain details look like toolbar buttons to HoughCircles. A real
        # HUD strip consists of FIVE+ nearly collinear, regularly spaced
        # circles close to the *outermost* edge, not scattered Atlas icons.
        toolbar = False
        if circles is not None:
            circle_data=circles[0]
            edge_x=55 if side=='left' else 60
            eligible=[(float(cx),float(cy)) for cx,cy,_radius in circle_data
                      if (cx<=edge_x if side=='left'
                          else cx>=strip.shape[1]-edge_x)]
            for cx,_cy in eligible:
                rows=sorted(cy for x,cy in eligible if abs(x-cx)<=9)
                longest=run=1
                for first,second in zip(rows,rows[1:]):
                    run=run+1 if 40<=second-first<=83 else 1
                    longest=max(longest,run)
                if longest>=5:
                    toolbar=True
                    break
        if toolbar:
            if side == "left":
                mask[95:max(96, h-135), :x1] = 0
            else:
                mask[95:max(96, h-135), x0:] = 0
    return mask


@dataclass
class Landmark:
    x: int
    y: int
    kind: str
    ident: int | None = None
    source: str = "manual"
    confidence: float = 1.0


def _vertical_beams(image: np.ndarray, low: tuple, high: tuple,
                    min_height: int = 11) -> list[tuple[int, int, int, float]]:
    """Return thin elongated colored streaks (x, y_bottom, height, evidence)."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(low), np.array(high))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (2, 11)))
    n, _labels, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    output = []
    for stat, center in zip(stats[1:n], centers[1:n]):
        _left, top, width, height, area = (int(v) for v in stat)
        if not (min_height <= height <= 135 and 1 <= width <= 18 and area >= 17):
            continue
        # The bottom of a beam is far above its associated structure's base.
        x = round(float(center[0]))
        output.append((x, top + height, height, float(area)))
    return output


def _green_base_below(green: np.ndarray, x: int, beam_bottom: int) -> tuple[int, int, float]:
    """Find a large green outline underneath a tower beam, not a tiny atlas node."""
    height, width = green.shape
    best = (x, beam_bottom + 75, 0.0)
    # A tower can lean sideways because the 3D atlas is oblique.
    # Tower height varies with Atlas zoom and perspective. v0.4 searched only
    # 52–119 pixels under the detected flame and missed shorter/taller towers.
    for dy in range(25, 176, 5):
        y = beam_bottom + dy
        x0, x1 = max(0, x - 46), min(width, x + 46)
        y0, y1 = max(0, y - 11), min(height, y + 12)
        if x0 >= x1 or y0 >= y1:
            continue
        roi = green[y0:y1, x0:x1]
        count = cv2.countNonZero(roi)
        if count < 15:
            continue
        ys, xs = np.where(roi > 0)
        horizontal_span = int(xs.max() - xs.min()) if len(xs) else 0
        # Grass and small green map nodes should not suggest a giant tower.
        if horizontal_span < 24:
            continue
        quality = count * min(1.0, horizontal_span / 42)
        if quality > best[2]:
            # The beam runs over the tower's stone shaft. Nearby grass glows
            # green too; do not drag its anchor 20+ px sideways into foliage.
            base_x = int(x0 + np.median(xs))
            best = (int(np.clip(base_x, x - 12, x + 12)),
                    int(y0 + np.median(ys)), quality)
    return best


def _fragmented_flame_towers(image: np.ndarray) -> list[Landmark]:
    """Recognize active towers when a cropped/tilted flame evades beam scans.

    In particular, the uppermost tower in the user's second screenshot has a
    broad green gear foot and a 25px-long orange flame, but not an unbroken
    11px streak inside the old narrow hue range. Neither its icon nor its
    green color alone is sufficient evidence: require both a *large* green
    foot and a separate, vertically elongated bright flame above the shaft.
    """
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    green=cv2.inRange(hsv,np.array([37,100,90]),np.array([90,255,255]))
    fire=cv2.inRange(hsv,np.array([0,90,115]),np.array([35,255,255]))
    fire=cv2.morphologyEx(fire,cv2.MORPH_OPEN,
                          cv2.getStructuringElement(cv2.MORPH_RECT,(2,5)))
    nf,_lf,fs,fc=cv2.connectedComponentsWithStats(fire,8)
    flames=[(int(cx),int(cy),int(bh),int(area))
            for (_x,_y,bw,bh,area),(cx,cy) in zip(fs[1:nf],fc[1:nf])
            if 3<=bw<=23 and bh>=22 and area>=95]
    if not flames:return []
    ng,_lg,gs,gc=cv2.connectedComponentsWithStats(green,8)
    output=[]
    height,width=image.shape[:2]
    for (left,top,bw,bh,area),(cx,cy) in zip(gs[1:ng],gc[1:ng]):
        left,top,bw,bh,area=map(int,(left,top,bw,bh,area))
        if not (25<=bw<=85 and 12<=bh<=70 and 95<=area<=1800):continue
        x,y=int(round(cx)),int(top+bh-4)
        if not (36<x<width-36 and 80<y<height-25):continue
        if not any(abs(x-fx)<=35 and 32<y-fy<145
                   for fx,fy,_flame_h,_flame_area in flames):continue
        output.append(Landmark(x,y,"Tower",source="elongated_flame_green_foot",
                               confidence=.86))
    return output


def _upper_cropped_towers(image: np.ndarray) -> list[Landmark]:
    """Suggest a partly clipped Tower when its wide green foot is still visible.

    Some screenshots end above an illuminated tower's crown. This is
    intentionally restricted to the exposed TOP edge, where the shaft is
    clipped by the screenshot rather than by the WORLD toolbar. The much
    smaller ~10px green map nodes must not qualify as tower feet.
    """
    h,w=image.shape[:2]
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    green=cv2.inRange(hsv,np.array([37,110,110]),np.array([89,255,255]))
    joined=cv2.morphologyEx(green,cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,7)))
    count,_labels,stats,centroids=cv2.connectedComponentsWithStats(joined,8)
    ui=game_ui_mask(image)
    results=[]
    for i in range(1,count):
        left,top,bw,bh,_area=map(int,stats[i])
        x,y=(round(float(v)) for v in centroids[i])
        if not (110<x<w-110 and 22<=y<=80 and
                29<=bw<=75 and 12<=bh<=45 and top<=60):
            continue
        if not ui[y,x]:
            continue
        true_green=int(cv2.countNonZero(
            green[max(0,top-4):min(h,top+bh+4),left:left+bw]))
        if true_green<72:
            continue
        # Require an upright, textured shaft above the broad green arc.
        # A large green decoration alone is insufficient.
        stripe=cv2.cvtColor(image[max(0,y-55):max(1,y-13),
                                      x-15:x+16],cv2.COLOR_BGR2GRAY)
        if stripe.shape[0]<22 or stripe.shape[1]<30:
            continue
        edgex=cv2.Sobel(stripe,cv2.CV_32F,1,0,ksize=3)
        if int(np.count_nonzero(np.abs(edgex)>55))<75:
            continue
        results.append(Landmark(x,top+bh-3,"Tower",
                     source="cropped_tower_shaft_green_foot",confidence=.82))
    return results


def _full_height_stone_towers(image: np.ndarray) -> list[Landmark]:
    """Find *unlit* stone obelisks by their shaft, crown and gold gear foot.

    A map-node green patch alone can never create a tower. The stone template
    came from the user's independently supplied clean inactive-tower example.
    Vertical-gradient matching tolerates variable background colour and zoom;
    gold gear evidence at the base distinguishes the building from mountains.
    All matches remain unconfirmed POI suggestions until clicked.
    """
    sample = _template("tower_template_inactive_tower.png")
    if sample is None or min(sample.shape[:2]) < 80:
        return []
    # Only the structure, not the neighboring mountains or atlas lines.
    reference = sample[10:159, 24:83]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    vertical = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, np.array([8, 65, 65]), np.array([32, 255, 255]))
    height, width = image.shape[:2]
    possibilities: list[Landmark] = []
    for scale in (.48, .52, .55, .60, .65, .70, .76):
        resized = cv2.resize(reference, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_AREA)
        template_gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32)
        template = cv2.Sobel(template_gray, cv2.CV_32F, 0, 1, ksize=3)
        response = cv2.matchTemplate(vertical, template, cv2.TM_CCOEFF_NORMED)
        local_max = cv2.dilate(response, np.ones((31, 31), np.uint8))
        yy, xx = np.where((response >= .35) & (response >= local_max - 1e-6))
        for top, left in zip(yy, xx):
            x = int(left + resized.shape[1] / 2)
            y = int(top + resized.shape[0] - round(14 * scale))
            if x < 32 or x >= width - 32 or y < 80 or y > height - 25:
                continue
            # Gear has a *broad* gold toothed edge, beneath a tall shaft.
            # UI gold rings have no such shaft and mountains no such foot.
            foot = gold[max(0, y - 13):min(height, y + 11), x - 28:x + 29]
            gold_pixels = int(cv2.countNonZero(foot))
            if gold_pixels < 95:
                continue
            score = float(response[top, left])
            possibilities.append(Landmark(x, y, "Tower",
                source="inactive_stone_shaft_gold_gear",
                confidence=min(.90, .71 + (score - .35) * 1.8
                               + min(.06, gold_pixels / 3500))))
    # A tower seen at multiple zooms should only have one square.
    result: list[Landmark] = []
    for item in sorted(possibilities, key=lambda p: -p.confidence):
        if not any(math.hypot(item.x - q.x, item.y - q.y) < 47 for q in result):
            result.append(item)
    return result


def _lit_stone_tower_templates(image: np.ndarray) -> list[Landmark]:
    """Find lit towers even when their flame is too short to form a beam.

    The shaft/crown pattern is from the supplied blue-base tower close-up.
    Require a sizable green OR blue base beneath that tall shaft. A small
    green dot or a badge without a vertical building never qualifies.
    """
    sample = _template("tower_template_blue_tower.png")
    if sample is None or min(sample.shape[:2]) < 90:
        return []
    core = sample[16:193,21:84]
    h,w=image.shape[:2]
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    green=cv2.inRange(hsv,np.array([37,90,90]),np.array([90,255,255]))
    blue=cv2.inRange(hsv,np.array([94,90,90]),np.array([128,255,255]))
    gold=cv2.inRange(hsv,np.array([8,70,70]),np.array([34,255,255]))
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY).astype(np.float32)
    vertical=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)
    proposals=[]
    for scale in (.45,.50,.55,.60,.65,.70,.75,.80,.85):
        resized=cv2.resize(core,None,fx=scale,fy=scale,
                           interpolation=cv2.INTER_AREA)
        refgray=cv2.cvtColor(resized,cv2.COLOR_BGR2GRAY).astype(np.float32)
        refedge=cv2.Sobel(refgray,cv2.CV_32F,0,1,ksize=3)
        match=cv2.matchTemplate(vertical,refedge,cv2.TM_CCOEFF_NORMED)
        peaks=cv2.dilate(match,np.ones((35,35),np.uint8))
        yy,xx=np.where((match>=.275)&(match>=peaks-1e-6))
        for top,left in zip(yy,xx):
            x=int(left+resized.shape[1]/2)
            y=int(top+resized.shape[0]-round(13*scale))
            if not (32<x<w-32 and 80<y<h-25):
                continue
            gear_roi=gold[y-22:y+8,x-30:x+31]
            green_pixels=int(cv2.countNonZero(green[y-22:y+8,x-30:x+31]))
            blue_pixels=int(cv2.countNonZero(blue[y-22:y+8,x-30:x+31]))
            gear_pixels=int(cv2.countNonZero(gear_roi))
            score=float(match[top,left])
            colored=((green_pixels>=125 or blue_pixels>=65) and
                     gear_pixels>=95 and score>=.34)
            # A grey/gold-foot tower has no green light and may appear
            # substantially different to the blue tower seed. Demand a
            # *large, bilateral* gold foot and a matching tall stone shaft;
            # golden path dashes along one side are not a substitute.
            gold_only=False
            if (not colored and score>=.275 and gear_pixels>=450 and
                    x>=110 and green_pixels<80 and blue_pixels<65):
                left_gold=int(cv2.countNonZero(gold[y-22:y+8,x-30:x-6]))
                right_gold=int(cv2.countNonZero(gold[y-22:y+8,x+6:x+31]))
                gold_only=left_gold>=90 and right_gold>=90
            if not (colored or gold_only):
                continue
            confidence=(.86 if gold_only else
                        min(.90,.75+max(0.,score-.34)*1.4+
                            min(.05,(green_pixels+blue_pixels)/4000)))
            proposals.append(Landmark(x,y,"Tower",
                           source=("stone_shaft_broad_gold_foot" if gold_only
                                   else "lit_stone_shaft_colored_gear"),
                           confidence=confidence))
    unique=[]
    for poi in sorted(proposals,key=lambda p:-p.confidence):
        if not any(math.hypot(poi.x-q.x,poi.y-q.y)<46 for q in unique):
            unique.append(poi)
    return unique


def _active_tower_templates(image: np.ndarray) -> list[Landmark]:
    """Identify illuminated green-foot towers missed by beam segmentation.

    Uses the actual multi-height active-tower reference, not a bare green
    circle. A tall orange flame *and* broad green illuminated base must be
    present together with a shaft match; ordinary green maps fail this test.
    """
    sample = _template("tower_template_active_tower.png")
    if sample is None or min(sample.shape[:2])<100:
        return []
    reference=sample[27:286,25:93]
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    green=cv2.inRange(hsv,np.array([37,100,90]),np.array([90,255,255]))
    flame=cv2.inRange(hsv,np.array([4,100,120]),np.array([28,255,255]))
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    h,w=image.shape[:2]
    candidates=[]
    for scale in (.45,.5,.55,.6,.65,.7,.75,.8,.85,1.):
        resized=cv2.resize(reference,None,fx=scale,fy=scale,
                           interpolation=cv2.INTER_AREA)
        if resized.shape[0]>=h or resized.shape[1]>=w:
            continue
        template=cv2.cvtColor(resized,cv2.COLOR_BGR2GRAY)
        response=cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED)
        maxima=cv2.dilate(response,np.ones((40,40),np.uint8))
        ys,xs=np.where((response>=.39)&(response>=maxima-1e-5))
        for top,left in zip(ys,xs):
            x=int(left+resized.shape[1]//2)
            y=int(top+resized.shape[0])
            if x<30 or x>=w-30 or y<75 or y>=h-25:
                continue
            green_roi=green[max(0,y-35):min(h,y+9),x-25:x+26]
            flame_roi=flame[max(0,top-8):min(h,top+45),x-17:x+18]
            if (cv2.countNonZero(green_roi)<120 or
                cv2.countNonZero(flame_roi)<70):
                continue
            confidence=min(.92,.81+max(0.,float(response[top,left])-.39)*2.5)
            candidates.append(Landmark(x,y,"Tower",source="active_tower_reference",
                                       confidence=confidence))
    unique=[]
    for poi in sorted(candidates,key=lambda p:-p.confidence):
        if not any(math.hypot(poi.x-q.x,poi.y-q.y)<65 for q in unique):
            unique.append(poi)
    return unique


def _purple_strongholds(image: np.ndarray) -> list[Landmark]:
    """Find sizeable clusters of glowing breach-purple structure, not small badges.

    A color heuristic can miss unlit Breach locations; every hit still needs
    manual confirmation before it becomes a network anchor.
    """
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([125, 93, 85]), np.array([169, 255, 255]))
    # The purple UI strip across the top can otherwise connect to a real
    # Breach structure after morphological closing, making the entire object
    # fail the old `top < 12` exclusion. Mask known HUD before clustering.
    mask[game_ui_mask(image)==0]=0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (23, 35)))
    count, _labels, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    found: list[Landmark] = []
    for i in range(1, count):
        left, top, bw, bh, area = (int(v) for v in stats[i])
        if not (35 <= bw <= 345 and 45 <= bh <= 260 and 185 <= area <= 23500):
            continue
        # Exclude the UI area at the top, where purple decorative buttons occur.
        if top < 12 or top+bh > h-10:
            continue
        roi = hsv[top:top+bh, left:left+bw]
        actual = cv2.inRange(roi, np.array([125, 110, 100]), np.array([169, 255, 255]))
        bright = int(cv2.countNonZero(actual))
        density=bright/max(1,bw*bh)
        # A large, central stronghold includes wide stretches of black
        # terrain between its glowing towers. The previous .035 density
        # cutoff rejected the whole structure while accepting a smaller
        # purple satellite beside it as a weak false landmark.
        if bright<100 or (density<.035 and
                          not (bright>=750 and density>=.022)):
            continue
        x = round(float(centers[i][0]))
        y = min(h-20, top+round(bh*.66))
        if 18 < x < w-18:
            found.append(Landmark(x, y, "Breach stronghold",
                                  source="breach_purple_structure",
                                  confidence=min(.84, .42 + bright/3500)))
    return found


def detect_landmarks(image: np.ndarray) -> list[Landmark]:
    """Towers and purple Breach strongholds by hand-made rules (the tower model uses them as a feature).

    Tall orange beams with broad green feet suggest towers; large clusters of breach-purple structure
    suggest Breach strongholds. (Halls / Cities are told apart elsewhere: atlas_detect.deadly_kind.)
    """
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([37, 110, 110]),
                        np.array([89, 255, 255]))
    output: list[Landmark] = []
    orange = _vertical_beams(image, (0, 120, 170), (24, 255, 255), min_height=9)
    for x, beam_bottom, beam_height, amount in orange:
        bx, by, green_strength = _green_base_below(green, x, beam_bottom)
        if green_strength >= 46:
            # A tower's distinctive green foot is useful anchor evidence.
            poi = Landmark(bx, by, "Tower", source="orange_beam_green_base",
                           confidence=min(.95, .58 + green_strength / 320))
            if 18 <= poi.x < w-18 and 25 <= poi.y < h-18:
                output.append(poi)

    # An earlier foliage-green footprint-only rule generated spurious towers.
    # Green color alone does NOT prove that an Atlas landmark is a tower.
    output.extend(_full_height_stone_towers(image))
    output.extend(_fragmented_flame_towers(image))
    output.extend(_upper_cropped_towers(image))
    output.extend(_lit_stone_tower_templates(image))
    output.extend(_active_tower_templates(image))
    output.extend(_purple_strongholds(image))

    ui_mask = game_ui_mask(image)
    output = [p for p in output if 0 <= p.x < w and 0 <= p.y < h
              and ui_mask[p.y,p.x] != 0]
    # Combine nearby beam fragments of the same kind.
    deduped: list[Landmark] = []
    for poi in sorted(output, key=lambda p: -p.confidence):
        if any((poi.x-p.x)**2 + (poi.y-p.y)**2 <
               (155 if poi.kind==p.kind=="Breach stronghold" else 92)**2 and poi.kind==p.kind
               for p in deduped):
            continue
        deduped.append(poi)
    return deduped
