import { Icons } from "@stark/ui/components/icons";

const ways = ["Bank transfer", "Debit card", "Crypto"];

export function Funding() {
  return (
    <section
      id="fund"
      className="mx-auto flex max-w-[1240px] scroll-mt-20 flex-col items-center gap-10 px-4 py-28 text-center sm:px-6 sm:py-[140px]"
    >
      <div className="flex flex-col items-center gap-3.5">
        <span className="text-xs tracking-[0.08em] text-brand uppercase">Funding</span>
        <h2 className="m-0 font-serif text-[clamp(34px,3.6vw,48px)] leading-[1.05] font-medium tracking-[-0.015em]">
          Fund it from whatever you hold.
        </h2>
        <p className="m-0 max-w-[540px] text-ink-2">
          Pay by bank transfer or card, or send almost any coin you already hold. It lands in your
          Stark balance in naira, ready for bills.
        </p>
      </div>
      <div className="flex flex-col items-center justify-center gap-3 sm:flex-row">
        <ul
          aria-label="Ways to add money"
          className="m-0 flex list-none flex-wrap justify-center gap-1.5 rounded-full bg-[#ECEDE8] p-1.5 text-[13px] font-medium"
        >
          {ways.map((w, i) => (
            <li key={w} className={`rounded-full px-3.5 py-2 ${i === 0 ? "bg-white" : ""}`}>
              {w}
            </li>
          ))}
        </ul>
        <Icons.ArrowRight size={20} className="rotate-90 text-ink-3 sm:rotate-0" />
        <span className="rounded-full bg-ink px-4 py-2.5 text-[13px] font-medium text-white">
          Your Stark balance
        </span>
      </div>
      <p className="m-0 max-w-[560px] text-[13px] text-ink-3">
        Naira conversion and the token itself come from our licensed bill-payment partner. Every
        payment comes with a receipt. Electricity starts with Ikeja Electric, plus airtime, data and
        cable TV through the same partner.
      </p>
    </section>
  );
}
