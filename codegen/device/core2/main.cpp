// M5-013 — Core2 entry point. Scaffolding only: boot, blank the panel, idle.
//
// No BLE (M5-014), no drawing toolkit (M5-015), no screens (M5-016). What this proves
// is that the tree builds, that shared/ links into a firmware image, and that the
// board comes up without a crash loop -- the last of which is the one thing here that
// genuinely needs a board.
//
// The background is --plane from the dashboard's dark palette, so the very first thing
// the panel ever shows is already the right colour rather than a default black that
// happens to look similar.

#include <M5Unified.h>

#include "../shared/frame.h"

namespace {

// dashboard/static/styles.css, dark block: --plane #0d0d0d.
constexpr int kPlane = 0x0d0d0d;

// Proof the shared parser linked, printed once over serial. A firmware that builds but
// silently dropped shared/ would otherwise look identical to one that did not.
void report_parser_linked() {
  codegen::Frame frame;
  const char kProbe[] = R"({"v":1,"s":1,"next":15,"dim":100})";
  const codegen::ParseResult result =
      codegen::parse(kProbe, sizeof(kProbe) - 1, &frame);
  M5.Log.printf("frame parser: %s, screen=%d, next=%ds\n",
                codegen::describe(result), frame.screen, frame.next_s);
}

}  // namespace

void setup() {
  auto config = M5.config();
  M5.begin(config);
  M5.Display.setBrightness(255);
  M5.Display.fillScreen(kPlane);
  report_parser_linked();
}

void loop() {
  M5.update();
  // Nothing to do yet. The poll loop arrives with the radio at M5-014; until then a
  // slow idle keeps the watchdog fed without pretending to be busy.
  delay(200);
}
