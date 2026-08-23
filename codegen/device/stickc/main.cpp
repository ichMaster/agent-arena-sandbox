// M5-013 — StickC Plus2 entry point. Scaffolding only: boot, blank the panel, idle.
//
// Deliberately the same shape as core2/main.cpp. The two diverge at M5-018, where the
// layouts do; until then a difference between these files would be a difference nobody
// chose.
//
// M5.begin() is what holds GPIO4 high on this board. Without it the StickC Plus2
// powers itself off the moment USB is unplugged, which is the kind of thing that reads
// as a dead battery rather than as a missing line of setup.

#include <M5Unified.h>

#include "../shared/frame.h"

namespace {

// dashboard/static/styles.css, dark block: --plane #0d0d0d.
constexpr int kPlane = 0x0d0d0d;

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
  // Landscape: 240x135. The vision doc's StickC layouts assume it, and rotating here
  // rather than per-screen means no renderer has to remember.
  M5.Display.setRotation(1);
  M5.Display.setBrightness(255);
  M5.Display.fillScreen(kPlane);
  report_parser_linked();
}

void loop() {
  M5.update();
  delay(200);
}
