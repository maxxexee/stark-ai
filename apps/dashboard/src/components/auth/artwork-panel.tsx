import { Artwork } from "@/components/auth/artwork";
import { ArtworkLabel } from "@/components/auth/artwork-label";
import { ArtworkSeam } from "@/components/auth/artwork-seam";

export function ArtworkPanel() {
  return (
    <aside className="relative hidden min-h-dvh p-4 lg:flex lg:p-6">
      <div className="relative w-full overflow-hidden rounded-card border border-border shadow-card">
        <Artwork />
        <ArtworkLabel />
      </div>

      <ArtworkSeam />
    </aside>
  );
}
