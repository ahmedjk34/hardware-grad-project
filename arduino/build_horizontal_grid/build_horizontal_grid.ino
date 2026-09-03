/*
 * Automatic level-0 build of every usable HORIZONTAL grid cell.
 *
 * This is a complete build_test_v1 sketch with a one-shot macro added on
 * boot.  Flash this sketch only when the machine is clear and supervised.
 * B 0 0 0 is deliberately omitted: [0,0] is the feeder.
 */

#include <stdio.h>

// Reuse the tested rig firmware, while giving its setup()/loop() private
// names so this sketch can run the build sequence once after boot.
#define setup buildTestV1Setup
#define loop buildTestV1Loop
#include "../build_test_v1/build_test_v1.ino"
#undef setup
#undef loop

void handleLine(char *line);

static void buildHorizontalGrid()
{
  // Mode changes require homed X/Y.  B itself then performs its normal
  // pick/place cycle and re-homes as defined by build_test_v1.
  char resetCommand[] = "0+";
  handleLine(resetCommand);

  char horizontalMode[] = "RR";
  handleLine(horizontalMode);

  // Horizontal is 3 columns by 10 rows. Build row-major, skipping only
  // feeder [0,0]; axis-only cells such as [0,1] are real placements.
  for (long row = 0; row <= 9; row++)
  {
    for (long col = 0; col <= 2; col++)
    {
      if (col == 0 && row == 0)
      {
        continue;
      }
      char command[16];
      snprintf(command, sizeof(command), "B %ld %ld 0", col, row);
      handleLine(command);
    }
  }
}

void setup()
{
  buildTestV1Setup();
  delay(2000); // give the operator time to release the machine after boot
  buildHorizontalGrid();
}

void loop()
{
  // Keep the normal serial console available after the one-shot sequence.
  buildTestV1Loop();
}
