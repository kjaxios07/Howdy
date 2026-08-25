// Kip's ask box, wrapped in a BorderBeam, in the Howdy palette.
//
// Adapted from the border-beam demo: the generic "Build anything..." chat
// input is replaced with Kip's actual placeholder and controls, and the
// hard-coded greys are swapped for the site's tokens so it reads as ours.
import { BorderBeam } from "@/components/ui/border-beam";
import { AtSign, ChevronRight, ArrowUp } from "lucide-react";

const CHIP =
  "inline-flex items-center gap-1 h-6 rounded-full bg-white/[0.04] " +
  "shadow-[inset_0_0_0_1px_rgba(255,255,255,0.02),inset_0_1px_0_0_rgba(255,255,255,0.04)]";

function AskBox() {
  return (
    <div
      className="relative w-[348px] max-w-full overflow-hidden rounded-[20px] bg-[#0D131D]
                 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.075),inset_0_0_50px_0_rgba(255,255,255,0.02)]"
    >
      <div className="flex h-[122px] flex-col p-[7px] pb-2">
        <div className={`${CHIP} ml-px w-fit px-1`}>
          <AtSign className="h-4 w-4 text-[#5B6E7E]" aria-hidden />
        </div>

        <div className="px-1 pt-4 text-[13px] leading-4 text-[#5B6E7E]">
          Ask me anything about living in Australia…
        </div>

        <div className="mt-auto flex items-center gap-2">
          <div className={`${CHIP} ml-px pl-2 pr-1.5 text-xs leading-[14px] text-[#93A5B5]`}>
            Any topic
            <ChevronRight className="h-4 w-4 rotate-90 opacity-60" aria-hidden />
          </div>
          <div className={`${CHIP} pl-2 pr-1.5 text-xs leading-[14px] text-[#93A5B5]`}>
            Brisbane
            <ChevronRight className="h-4 w-4 rotate-90 opacity-60" aria-hidden />
          </div>
          <div className={`${CHIP} ml-auto h-7 w-7 justify-center px-2`}>
            <ArrowUp className="h-4 w-4 text-[#2FD3AE]" aria-hidden />
          </div>
        </div>
      </div>
    </div>
  );
}

export default function KipBeamDemo() {
  return (
    <div
      className="mx-auto flex min-h-[360px] w-[600px] max-w-full items-center
                 justify-center rounded-3xl bg-[#070B12]"
    >
      <BorderBeam size="md" colorVariant="colorful">
        <AskBox />
      </BorderBeam>
    </div>
  );
}
