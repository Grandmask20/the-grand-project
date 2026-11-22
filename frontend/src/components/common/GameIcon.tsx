import edit from "@/assets/poe/fouriconedit.png";
import search from "@/assets/poe/iconsearch.png";
import folder from "@/assets/poe/optionsiconfolder.png";
import refresh from "@/assets/poe/optionsiconrefresh.png";
import { cn } from "@/utils/Cn";

const ICONS = { edit, search, folder, refresh };

/** One of the game's own interface icons (user: PoE2's elements in place of generic ones), sized by `className`. */
export function GameIcon({ name, className }: { name: keyof typeof ICONS; className?: string }) {
	return <img src={ICONS[name]} alt="" aria-hidden="true" className={cn("shrink-0 object-contain", className)} />;
}
