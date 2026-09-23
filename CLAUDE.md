# CLAUDE.md

For agents working in this repository. User-facing install steps, feature lists
and the interface inventory live in `README.md`. Do not repeat them here.

Home Assistant custom integration for Zhongshan Water (中山公用水务) usage and
billing. Independent, unofficial client — not affiliated with the utility.

## Where to edit

| File | Role |
|------|------|
| `custom_components/zswater/__init__.py` | Entry setup/unload, update listener, device removal |
| `custom_components/zswater/config.py` | Read IP family / interval / history window; bound HA `ClientSession` |
| `custom_components/zswater/config_flow.py` | Network step, login (手机号/密码/短信验证码), options (add/bind 户号, settings), reauth |
| `custom_components/zswater/coordinator.py` | `ZSWaterCoordinator` |
| `custom_components/zswater/sensor.py` | `_SENSOR_DEFINITIONS` table and entities |
| `custom_components/zswater/binary_sensor.py` | 欠费状态 |
| `custom_components/zswater/const.py` | Suffixes, config keys, defaults, step ids |
| `custom_components/zswater/zswater_client/const.py` | BASE_URL, endpoints, envelope status codes |
| `custom_components/zswater/zswater_client/__init__.py` | `ZSWaterClient` — usable without Home Assistant |
| `custom_components/zswater/zswater_client/models.py` | Payload parsing, `MeterSnapshot` |
| `custom_components/zswater/zswater_client_demo.py` | Standalone client demo |
| `custom_components/zswater/strings.json` | Chinese UI source |
| `custom_components/zswater/translations/zh-Hans.json` | Same values as `strings.json` |
| `custom_components/zswater/translations/en.json` | English |
| `tests/` | Behaviour tests; do not change them to accommodate a refactor |

Data flow: pick IP family → 手机号 + 密码 → portal texts a 短信验证码 → submit it
to log in → write token into the config entry → coordinator fetches on the
refresh interval → `_SENSOR_DEFINITIONS` creates entities.

## Protocol facts (do not re-derive from scratch)

These come from `https://smartbi.zsws.com.cn/js/main.<hash>.js`. If the portal is
re-released, re-read that bundle before editing `zswater_client/`.

- Every call posts a single JSON document: `requestPara=<json>` as a form body
  (`+` → `%2B`, `&` → `%26`, the rest raw), or as a GET query parameter.
- The web client injects `token`, `waterCorpId=3`, `UNID=""`, `areaId=0`,
  `accountType="XJ"`, `apiType="JSAPI"`, `appVersion="1.0.2"` **over** the
  caller's params. `ZSWaterClient._payload` must keep doing the same.
- Envelope: `{status, errcode, errmsg, message, data}`. `status == 0` is success,
  `status == 11` means the token is gone, anything else is a business error whose
  `message` is user-facing. Some endpoints answer HTTP 500 on missing fields.
- Passwords are lowercase hex MD5 (blueimp-md5 default export), see `md5_hex`.
- `getMeterInfoByUId` is counter-intuitive: `nextto`/`nextreaddate` are **本期**,
  `lastto`/`lastreaddate` are **上期**.
- `queryUserMeterList` returns **only 户号 bound inside the portal**, and the
  portal asks for it with exactly `{"UNID": ""}` — byte-for-byte what
  `async_get_accounts` sends. An empty list therefore means "nothing bound", not
  "bad request"; the portal's own client warns 「您还没有绑定户号，请去绑定户号」.
  A 户号 visible in the mobile app / 小程序 is a different front-end with its own
  binding and does not show up here. Do not "fix" the empty case by changing the
  request, and keep `STEP_NO_ACCOUNT` in the flow so the user is told what to do.
- Binding a 户号 (`/#/queryInfo`, reached from the empty state's 「绑定户号」 or
  from 综合查询 → 绑定户号). The form has four required fields — 户号, 户名,
  手机号, 验证码 — and **no 图形验证码**; its `发送` button texts a code through
  `sendAuthCode/v4`. Observed live sequence:
  `sendAuthCode/v4` → `getMeterInfoByUId/v1` (`{userID, meterName, ...}`) →
  `addMeter/v2` (`{meterName, meterNumber, meterMobile, meterAlert: 0,
  meterNick: "", code, meterAddress}`). So `code` there is the **短信验证码**,
  the same meaning it has on the login form. An earlier note in this file called
  it a captcha value; that was wrong.

## Do not break

Write rules. Read the source files. Do not copy lists or numbers into this file.

- The login is 手机号 + 密码 + 短信验证码, matching the portal's own card field
  for field. There is **no** 图形验证码: the portal's `captchaUrl`/`keyDate`
  state is dead code (`this.state.captchaUrl;` is a bare statement and no image
  is rendered). Do not reintroduce a captcha step, and do not re-add a login
  menu — the two other routes in `LoginType` need credentials a user cannot
  obtain (see that enum's docstring).
- Do not rename sensor suffixes, entity unique ids, or device identifiers.
  Suffixes live in the top-level `const.py`; the table lives in `sensor.py`.
- Adding a sensor = one row in `_SENSOR_DEFINITIONS` + `strings.json` +
  `translations/zh-Hans.json` + `translations/en.json`.
- Keep `zswater_client/` free of Home Assistant imports — `tests/test_config_flow_helpers.py`
  asserts this, and `zswater_client_demo.py` depends on it.
- Plaintext passwords must never be written to `ConfigEntry.data`. Only the token
  is persisted; `async_setup_entry` strips a legacy `CONF_PASSWORD`. The login
  password lives in flow instance state (`_pending_password`) for the two steps
  the portal needs it across, and nowhere else.
- Do not change `tests/` to accommodate a refactor.

When you change one place, change the coupled places too:

| You change | Also touch |
|------------|------------|
| New sensor | `const.py` suffix + `_SENSOR_DEFINITIONS` + the translation trio |
| New login route | `LoginType` + the step in `config_flow.py` + the translation trio |
| A step's `description`/`title`/`menu_options` | the matching `async_show_form`/`async_show_menu` call — `tests/test_flow_translations.py` cross-checks both directions |
| Portal payload field | `zswater_client/models.py` fallback chain + `tests/test_models.py` |
| Endpoint path | `zswater_client/const.py` |

## How to test

```bash
python -m pytest -q
```

`tests/test_client.py` and `tests/test_models.py` need only `aiohttp` and
`pytest`. `tests/test_config_flow_helpers.py` skips itself unless
`homeassistant` is importable.

CI jobs: Tests, hassfest, HACS. Treat `.github/workflows/` as the source of
truth for matrix and versions.

## Traps

- `OptionsFlow` intentionally defines no `__init__` — Home Assistant constructs
  options flows itself and the base signature has changed between releases.
- `strings.json` is the Chinese source; `zh-Hans.json` duplicates it. Keep both in
  sync when editing UI copy.
- Home Assistant dispatches a menu choice itself: `data_entry_flow` consumes
  `next_step_id` and calls `async_step_<id>`, never the menu's own method. A
  menu option whose id is not a step id fails as an error dialog with no text,
  and an option with no `menu_options` label renders blank.
  `tests/test_flow_translations.py` checks both.
- A step description differing from what the flow renders is invisible to every
  Python-level test — the frontend formats it. That is what the same module is
  for; run it before touching `strings.json`.
