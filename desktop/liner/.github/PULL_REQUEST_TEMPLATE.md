## What

<!-- What changes for the user, in one or two sentences. -->

## Why

<!-- The problem this solves. Link the issue: "Closes #123". -->

## How

<!-- The approach, and anything a reviewer should look at first. -->

## Checklist

- [ ] `pnpm check` passes
- [ ] Follows [AGENTS.md](../AGENTS.md): no comments in code, files under 150 lines, imports only point down the FSD layers, no `any`
- [ ] Screenshot or recording attached for UI changes
- [ ] Tested in the running app, not only in unit tests
- [ ] [docs/PRIVACY.md](../docs/PRIVACY.md) updated if this changes what the app sends off the device
- [ ] New strings added to `en.json` (other languages are optional)
