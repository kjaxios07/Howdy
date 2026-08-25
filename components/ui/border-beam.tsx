// Re-export wrapper so the rest of the app imports from "@/components/ui/border-beam"
// rather than the package directly. If we ever swap the implementation, only
// this file changes.
//
// NOTE: this repo is not a React project yet — see components/README.md.
// These files are staged for the migration described there.
import { BorderBeam } from "border-beam";
import type {
  BorderBeamProps,
  BorderBeamSize,
  BorderBeamTheme,
  BorderBeamColorVariant,
} from "border-beam";

export type {
  BorderBeamProps,
  BorderBeamSize,
  BorderBeamTheme,
  BorderBeamColorVariant,
};

export { BorderBeam };
export default BorderBeam;
