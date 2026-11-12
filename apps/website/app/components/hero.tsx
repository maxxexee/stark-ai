import { buttonVariants } from "@stark/ui/components/button";
import { Icons } from "@stark/ui/components/icons";
import { cn } from "@stark/ui/utils/cn";
import { links } from "~/lib/links";

const chat = [
  { who: "Mum", text: "light just went, meter is on zero", me: false, inset: "ml-4 sm:ml-10" },
  { who: "You", text: "told stark to top up 5k", me: true, inset: "mr-4 sm:mr-10" },
  { who: "Mum", text: "can it do my airtime too?", me: false, inset: "ml-4 sm:ml-10" },
  { who: "You", text: "works with any bill", me: true, inset: "mr-6 sm:mr-20" },
];

export function Hero() {
  return (
    <section className="relative mx-auto flex max-w-[1240px] flex-col items-center gap-5 px-4 pt-10 pb-20 text-center sm:px-6 sm:pt-16 sm:pb-[120px]">
      <span className="rounded-full bg-paper-2 px-3 py-1 text-xs text-ink-2">
        Built on <strong className="font-semibold text-ink">NEAR</strong>
      </span>
      <h1 className="relative z-0 m-0 font-serif text-[clamp(40px,5.4vw,72px)] leading-[1.04] font-normal tracking-[-0.02em]">
        <span className="swash">Keep the lights on,</span>
        <br />
        without leaving the chat
      </h1>
      <p className="m-0 max-w-[520px] text-ink-2">
        One voice note to your agent and the token is back. Paid from your Stark balance, inside
        limits you set.
      </p>

      <div className="relative mt-4 h-[300px] w-full max-w-[760px] overflow-hidden rounded-[28px] bg-[linear-gradient(160deg,#3B2417_0%,#1D130E_55%,#120C09_100%)] text-left">
        <div
          aria-hidden="true"
          className="absolute -top-20 -left-15 size-[260px] rounded-full bg-brand-warm opacity-55 blur-[60px]"
        />
        <div
          aria-hidden="true"
          className="absolute -top-2.5 left-10 size-[120px] rounded-full bg-[#FFD7A8] opacity-70 blur-[18px]"
        />
        <div
          aria-hidden="true"
          className="absolute -top-10 right-15 hidden h-[140px] w-[220px] rounded-[14px] bg-[#2A2B30] opacity-80 sm:block"
        />
        <div
          aria-hidden="true"
          className="absolute -bottom-15 left-10 h-[200px] w-[150px] -rotate-12 rounded-[10px] bg-[#4A3426]"
        />
        <div
          aria-hidden="true"
          className="absolute right-[90px] bottom-[30px] hidden h-[120px] w-[90px] flex-col items-center justify-center gap-2 rounded-xl border-2 border-[#44454B] bg-[#2F2F33] sm:flex"
        >
          <span className="h-6 w-14 rounded bg-[#9FD3A4] opacity-85" />
          <span className="h-[34px] w-14 rounded bg-[#3D3E44]" />
        </div>
        <div className="absolute inset-0 flex flex-col gap-3.5 px-4 py-7 text-[15px] sm:px-10">
          {chat.map((m) => (
            <div
              key={m.text}
              className={`flex flex-col gap-0.5 ${m.me ? "items-end self-end" : "self-start"} ${m.inset}`}
            >
              <span className="text-[11px] text-[#E8DCCF]">{m.who}</span>
              <span
                className={`rounded-2xl px-3 py-1.5 ${m.me ? "bg-brand text-white" : "bg-bubble text-ink"}`}
              >
                {m.text}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap justify-center gap-2 text-[13px]">
        <a href={links.telegram} className={cn(buttonVariants({ variant: "ink" }), "min-h-10")}>
          Open the Telegram bot
        </a>
        <a href={links.getStarted} className={cn(buttonVariants({ variant: "paper" }), "min-h-10")}>
          Set up Stark
        </a>
      </div>
      <span className="text-xs text-ink-3">
        Works by voice note, text, or a Talk button on the wall
      </span>

      <a
        href={links.talk}
        className="absolute right-8 bottom-10 hidden -rotate-6 flex-col items-center text-ink no-underline md:flex"
      >
        <span className="flex size-16 items-center justify-center rounded-full bg-brand text-white shadow-[0_10px_30px_rgba(194,65,12,0.35)]">
          <Icons.Mic size={28} />
        </span>
        <span className="-mt-2 rounded-full bg-white px-2 text-xs shadow-[0_2px_6px_rgba(15,17,21,0.12)]">
          talk
        </span>
      </a>
    </section>
  );
}

export function Intro() {
  return (
    <section className="mx-auto flex max-w-[1240px] flex-wrap items-end justify-between gap-8 px-4 pt-6 pb-24 sm:px-6 sm:pt-14 sm:pb-[120px]">
      <h2 className="m-0 flex-[1_1_520px] font-serif text-[clamp(40px,5.6vw,76px)] leading-[1.02] font-medium tracking-[-0.02em]">
        Meet Stark, the agent that pays your bills by voice.
      </h2>
      <div className="flex flex-[0_1_420px] flex-col gap-5">
        <p className="m-0 text-ink-2">
          Send a voice note. Stark pays your electricity, airtime, data and TV bills from your
          balance, and never spends past the limits you set. Prepaid electricity comes first.
        </p>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3 text-sm">
          <a href={links.getStarted} className={buttonVariants({ variant: "ink", size: "md" })}>
            Start with Stark
          </a>
          <a href={links.telegram} className="font-medium text-ink no-underline">
            Try the Telegram bot
          </a>
        </div>
      </div>
    </section>
  );
}
