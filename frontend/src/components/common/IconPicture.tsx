import { useAppClient } from "@/hooks/app/UseAppClient";
import { cn } from "@/utils/Cn";

/** An icon type's picture (the game's art when the app has it). */
export function IconPicture({ name, size = 22, className }: { name: string; size?: number; className?: string }) {
	const app = useAppClient();
	return (
		<img
			src={app.iconUrl(name, size * 2)}
			alt=""
			width={size}
			height={size}
			loading="lazy"
			className={cn("shrink-0", className)}
		/>
	);
}
