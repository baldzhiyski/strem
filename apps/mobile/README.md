# strem-mobile

React Native + Expo app for STREM's Race OS: name a race or challenge, and the race
team plans training, fueling, gear, logistics and strategy for it
(`../../docs/product.md`).

## Navigation

- **Mission** — photo hero with countdown and phase, today's session, the race-team
  brief with its evidence, readiness by layer, the training tracker (including the
  weeks before the plan), what's coming up and race-day conditions. Several races,
  with a switcher.
- **Plan** — periodized weeks to race day, session detail and status, the adapt sheet
  (tell the race team what changed → a proposal you accept or reject), why this plan.
- **Race Lab** — course (map, elevation, climbs), fuel, gear, logistics, strategy.
  Every layer shows whether the race engine or the AI made it.
- **Team** — ask the race team; what it knows and what's missing.
- **You** — body & health basics, race history, connected sources, check-ins, races,
  mission data export/delete, debrief.

Race setup is seven steps: sport → race (place search, month-jump calendar) →
demands → goal → cover photo (openly licensed, credited) → starting point → commit.

## Data honesty

Everything comes from the backend APIs; there is no sample race or fixture data at
runtime. Unknown facts stay unknown. When the AI race team is unavailable (no key or
no credit) the race engine builds every layer and the app says why.

## Code layout

```text
app/
  (auth)/ (legal)/ (onboarding)/   sign-in, policy acceptance, two-step onboarding
  (app)/                            the five tabs plus setup, session, history, check-in,
                                    integrations, missions, mission-data, debrief
components/
  ui/        design system: kit, charts, fields, photo hero, sheet, icon
  mission/   hero and Mission sections        plan/   session rows, adapt sheet
  lab/       layer view, course               team/   rich text
  shell/     tab bar / side rail
lib/
  api/       typed clients (auth, user, race missions, layers, plans, AI, enrichment)
  race/      race context, readiness, tracker series, formats, sports, builder
e2e/         Playwright browser tests against real services
```

## Run

Start the backend first ("Run it yourself" in the root `README.md`, including every
setting and Strava), then:

```bash
npm install
npm run web          # Expo web
```

The API defaults to `http://localhost:8000/v1`; override with
`EXPO_PUBLIC_API_URL`. Restart Expo after changing `EXPO_PUBLIC_*` settings.

Native development: `npm run ios` / `npm run android`.

## Checks

```bash
npx tsc --noEmit
npm run lint
npm test -- --runInBand
```

## Browser tests

`e2e/` runs real auth, user, training and gateway processes on disposable SQLite
databases (no AI service) and a production-mode Expo bundle, at 390 px and 1440 px:
login, the seven-step race setup through commit, course GPX upload with reload, and
export + permanent delete.

```powershell
$env:STREM_TEST_BACKEND_PYTHON = 'C:/path/to/venv/Scripts/python.exe'  # with all four services' requirements
npm.cmd run test:e2e
```

Ports 9510–9514 must be free. Screenshots land in ignored `test-results/`; traces are
off so tokens are never retained.

## Review gates

Contracts, source ingestion, privacy, health-adjacent AI behaviour and deployment
need the reviews defined in the workspace `AGENTS.md`. Browser tests don't replace
native-device, screen-reader and real-athlete usability checks.
