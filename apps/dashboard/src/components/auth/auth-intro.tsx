import { Eyebrow } from "@stark/ui/components/eyebrow";
import { Link } from "@tanstack/react-router";

export function AuthIntro({
  eyebrow,
  title,
  prompt,
  link,
}: {
  eyebrow: string;
  title: string;
  prompt: string;
  link: { to: "/login" | "/start"; label: string };
}) {
  return (
    <div className="mt-10 sm:mt-12">
      <Eyebrow>{eyebrow}</Eyebrow>
      <h1 className="m-0 mt-1.5 text-2xl font-semibold tracking-tight text-fg">
        {title}
        <span className="text-brand">.</span>
      </h1>
      <p className="m-0 mt-1.5 text-base text-muted-foreground">
        {prompt}{" "}
        <Link to={link.to} className="font-medium text-brand no-underline hover:text-brand-soft">
          {link.label}
        </Link>
      </p>
    </div>
  );
}
