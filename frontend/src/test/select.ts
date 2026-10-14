import { screen } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";

/** Picks an option from a `Select` (base-ui): open the trigger, click the option by its label. */
export async function chooseOption(
  user: Pick<UserEvent, "click">,
  trigger: HTMLElement,
  option: string | RegExp,
) {
  await user.click(trigger);
  await user.click(await screen.findByRole("option", { name: option }));
}
