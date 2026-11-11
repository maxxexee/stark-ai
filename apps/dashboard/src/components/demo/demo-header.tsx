import { Button } from "@stark/ui/components/button";
import { LogoMark } from "@stark/ui/components/logo";
import { Link } from "@tanstack/react-router";

export function DemoHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-border bg-canvas/85 pt-[env(safe-area-inset-top)] backdrop-blur-lg">
      <div className="mx-auto flex h-13 w-full max-w-190 items-center gap-2.5 px-4 sm:px-6">
        <a
          href="https://hellostark.xyz"
          aria-label="Stark home"
          className="flex items-center gap-2.5 text-fg no-underline hover:text-fg"
        >
          <LogoMark size={20} cutout="#ffffff" />
          <span className="text-base font-semibold">Stark</span>
        </a>
        <span aria-hidden="true" className="text-faint">
          /
        </span>
        <span className="text-base text-fg-2">Sample account</span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="ghost" size="sm" nativeButton={false} render={<Link to="/login" />}>
            Log in
          </Button>
          <Button variant="brand" size="sm" nativeButton={false} render={<Link to="/start" />}>
            Get started
          </Button>
        </div>
      </div>
    </header>
  );
}
