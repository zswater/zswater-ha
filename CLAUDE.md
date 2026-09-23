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
| `custom_components/zswater/config_flow.py` | Network step, three login routes, options (add/bind 户号, settings), reauth |
| `custom_components/zswater/captcha.py` | One-shot HTTP endpoint serving 图形验证码 images to the login form |
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

Data flow: pick IP family → one of three login routes → write token into the
config entry → coordinator fetches on the refresh interval → `_SENSOR_DEFINITIONS`
creates entities.

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

## Do not break

Write rules. Read the source files. Do not copy lists or numbers into this file.

- Do not drop a login route. The list is `LoginType` in `zswater_client/const.py`.
- Do not rename sensor suffixes, entity unique ids, or device identifiers.
  Suffixes live in the top-level `const.py`; the table lives in `sensor.py`.
- Adding a sensor = one row in `_SENSOR_DEFINITIONS` + `strings.json` +
  `translations/zh-Hans.json` + `translations/en.json`.
- Keep `zswater_client/` free of Home Assistant imports — `tests/test_config_flow_helpers.py`
  asserts this, and `zswater_client_demo.py` depends on it.
- Do not widen the captcha endpoint's exposure: it must stay single-use, TTL-bound
  (`CAPTCHA_TTL`) and keyed by an unguessable token.
- Plaintext passwords must never be written to `ConfigEntry.data`. Only the token
  is persisted; `async_setup_entry` strips a legacy `CONF_PASSWORD`.
- Do not change `tests/` to accommodate a refactor.

When you change one place, change the coupled places too:

| You change | Also touch |
|------------|------------|
| New sensor | `const.py` suffix + `_SENSOR_DEFINITIONS` + the translation trio |
| New login route | `LoginType` + `LOGIN_MENU_TO_STEP` in `config_flow.py` + the translation trio |
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
- The captcha view sets `requires_auth = False` on purpose (a plain link click
  carries no bearer token). Do not "fix" it to `True`; see the module docstring.
- `_extract_unionid` accepts both a bare `unionid` and a pasted whole URL. Keep
  that tolerance — the README tells users to paste either.
