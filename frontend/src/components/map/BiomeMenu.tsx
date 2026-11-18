import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Meta } from "@/domain/app/Meta";
import { plural } from "@/utils/Format";

interface Props {
	x: number;
	y: number;
	maps: number;
	meta: Meta;
	onChoose: (biome: string | null) => void;
}

/** After a lasso: what the maps inside are (a city type, a Breach stronghold, or no biome). */
export function BiomeMenu({ x, y, maps, meta, onChoose }: Props) {
	return (
		<DropdownMenu open onOpenChange={(open) => !open && onChoose(null)}>
			<DropdownMenuTrigger asChild>
				<span className="pointer-events-none absolute size-px" style={{ left: x, top: y }} />
			</DropdownMenuTrigger>
			<DropdownMenuContent align="start">
				<DropdownMenuLabel>{plural(maps, "map")} inside: their biome</DropdownMenuLabel>
				{meta.biomes.map((b) => (
					<DropdownMenuItem key={b} onSelect={() => onChoose(b)}>
						{b}
					</DropdownMenuItem>
				))}
				<DropdownMenuSeparator />
				<DropdownMenuItem onSelect={() => onChoose("")}>Not a biome (clear these maps)</DropdownMenuItem>
				<DropdownMenuItem onSelect={() => onChoose(null)}>Cancel</DropdownMenuItem>
			</DropdownMenuContent>
		</DropdownMenu>
	);
}
