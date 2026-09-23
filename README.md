# 中山公用水务 HA 集成（zswater-ha）

[![hacs](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![license](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![unofficial](https://img.shields.io/badge/status-unofficial-orange.svg)](#-非官方声明unofficial)

Home Assistant 自定义集成，读取**中山公用水务**（中山公用水务投资有限公司）网上营业厅的水费与用水数据。

---

## ⚠️ 非官方声明（Unofficial）

**本项目是非官方的第三方项目，由个人开发者出于自用目的独立编写。**

- 本项目与**中山公用水务投资有限公司**及其关联企业**没有任何隶属、合作、委托、授权或认可关系**；
- 官方**未**参与本项目的开发、测试或发布，也**未**对本项目提供任何支持或背书；
- 本项目不代收水费、不代缴水费、不修改任何账单，也不能代表你与官方办理任何业务；
- 仓库名称、作者、代码与 Issue 区均**不代表官方立场**；涉及水费、水表、缴费、过户等业务，请以官方营业厅、官方微信公众号及服务热线 `0760-96968` 为准；
- 数据均通过公开可访问的网上营业厅接口获取，**仅供户主本人查询自己名下的用水数据**使用。

如权利方认为本项目存在不当之处，可通过仓库 Issue 联系，开发者将及时处理。

---

## 参考与致谢

本项目参照 [windyboy/china_southern_power_grid_stat](https://github.com/windyboy/china_southern_power_grid_stat)（南方电网电费数据 HA 集成）的架构编写，感谢原项目提供参考。

---

## 支持功能

- ✅ 查询**欠费金额**、本期账单、账户余额
- ✅ 查询**上期抄表读数**、**本期抄表读数**（含抄表日期）
- ✅ 查询本期用水量、本期水费、违约金、本期应缴总额
- ✅ 查询历史抄表/缴费记录（回溯天数可配置）
- ✅ 一个账号可接入多个户号，每个户号一个独立设备
- ✅ 三种登录方式：手机号密码、微信 unionid、短信验证码注册
- ✅ 全程 GUI 配置，无需编辑 YAML
- ✅ 登录态失效自动提示重新登录（reauth）
- ✅ 可选网络协议（自动 / 仅 IPv4 / 仅 IPv6），应对部分网络下 IPv6 不可达

### 传感器列表

| 传感器 | 数据来源字段 | 说明 |
|---|---|---|
| 欠费金额 | `fullAmount` | 户号下总欠费 |
| 本期账单 | `arrearage` | |
| 账户余额 | `balance` | |
| **上期抄表读数** | `lastto` / `lastRead` | m³，累计值 |
| **本期抄表读数** | `nextto` / `currentRead` | m³，累计值 |
| 本期用水量 | `consumedVolume` | m³，缺失时用两期读数相减 |
| 本期水费 | `defaultAmount` | 元 |
| 违约金 | `penalty` / `znj` | 元 |
| 本期应缴总额 | `payablePrincipal` | 元 |
| 上期抄表日 | `lastreaddate` | |
| 本期抄表日 | `nextreaddate` | |
| 抄表历史（诊断） | 全部账单行 | 状态为记录条数，属性 `history` 含明细 |
| 欠费状态（binary_sensor） | `fullAmount` | 有欠费时 `on` |

---

## 安装

### 方式一：HACS

1. HACS → 集成 → 右上角三个点 → 自定义存储库
2. 仓库地址填 `https://github.com/zswater/zswater-ha`，类别选「集成」
3. 搜索「Zhongshan Water」安装并重启 Home Assistant

### 方式二：手动安装

把 `custom_components/zswater` 整个目录复制到 Home Assistant 配置目录的
`custom_components/` 下，重启 Home Assistant。

### 环境要求

- Home Assistant **2024.1** 或更高版本
- 无需额外 Python 依赖（密码哈希使用标准库 `hashlib`）

---

## 配置流程

`设置 → 设备与服务 → 添加集成 → 搜索「中山公用水务 / Zhongshan Water」`

1. **网络设置** —— 选择网络协议（默认「自动选择」，登录异常时改「仅 IPv4」）
2. **登录方式** —— 见下节
3. **选择户号** —— 勾选要接入 HA 的户号（可多选）

### 登录方式

#### 1. 手机号密码登录（推荐，最稳定）

填写手机号、密码、图形验证码。

图形验证码是服务端生成的图片，Home Assistant 的表单无法内嵌图片，因此集成会把验证码
图片**临时**挂在 `/api/zswater/captcha/<一次性随机令牌>` 上，表单说明里有可直接点击的链接：

1. 点表单里的「点此查看验证码」链接，读出 4 位数字
2. 回到表单填入，提交

验证码 5 分钟内有效、只能查看一次；如果填错了重新提交，集成会自动换一张新验证码。

#### 2. 微信扫码登录

适用于平时用微信公众号查水费、没有单独密码的情况：

1. 微信关注「**中山公用水务**」公众号
2. 点菜单「在线服务」→「查询缴费」，进入网上营业厅
3. 复制地址栏中 `unionid=` 后面那一段
4. 粘贴到集成表单（直接粘贴整条含 `unionid=` 的网址也可以，集成会自动提取）

#### 3. 短信验证码注册

> **重要说明**：中山公用水务网上营业厅**不提供「仅凭短信验证码登录」**的功能。
> 短信验证码只用于**注册账号**和**绑定户号**。集成如实实现这两条路径：
>
> - 「短信验证码注册」会发送验证码，填写验证码 + 新密码后**注册并自动登录**；
>   之后你也可以改用「手机号密码登录」。
> - 「绑定新户号」会向水表登记的手机号发送验证码。

### 参数设置

集成页面「配置」→ 可修改：

- **刷新间隔**（秒，默认 21600 = 6 小时，最低 60）
- **用水记录回溯天数**（默认 120 天，范围 30–1095）
- **网络协议**

### 选项菜单

- **添加已绑定的户号** —— 把营业厅里已绑定但还没接入 HA 的户号加入进来
- **绑定新户号** —— 在营业厅绑定一个尚未登记的户号（户号 + 户名 + 水表登记手机号 + 短信验证码）
- **参数设置** —— 同上

---

## 一些技术细节

### 接口来源

所有接口路径、请求字段与响应字段均从网上营业厅前端产物
`https://smartbi.zsws.com.cn/js/main.<hash>.js` 中提取，并逐项核对，**不是猜测**：

- **入口**：`https://smartbi.zsws.com.cn`（网上营业厅 SPA）
- **请求封装**：所有接口把参数打包成一个 JSON，格式为
  - `POST`：表单体 `requestPara=<JSON>`，其中 `+` 转义为 `%2B`、`&` 转义为 `%26`，其余 JSON 原样发送
  - `GET`：`requestPara=<JSON>` 作为查询参数
- **公共参数**：前端在每次请求都会**覆盖式**注入
  `token`、`waterCorpId=3`、`UNID=""`、`areaId=0`、`accountType="XJ"`、`apiType="JSAPI"`、`appVersion="1.0.2"`
- **响应信封**：

```json
{ "status": 0, "errcode": 0, "errmsg": "", "message": "", "data": null }
```

`status = 0` 表示成功；`status = 11` 表示登录态失效（前端此时会清理 token 并跳回登录页，
集成将其映射为「需要重新登录」）；其它非 0 值为业务错误，`message` 是给用户看的原文。
少数接口在缺少必填参数时会直接返回 HTTP 500 而不是信封。

- **密码**：前端用 blueimp-md5 对密码做客户端哈希，即**小写十六进制 MD5**

### 已实现的主要接口

| 用途 | 方法 | 路径 |
|---|---|---|
| 图形验证码 | GET | `/iwater/nt/validateCode.json` |
| 密码登录 | POST | `/iwater/nt/wt/login.json` |
| 微信 unionid 登录 | POST | `/iwater/nt/wt/logining.json` |
| 注册 | POST | `/iwater/iwaterapi/nt.json` |
| 发送短信验证码 | GET | `/iwater/v1/usercenter/nt/sendAuthCode/v4.json` |
| 户号列表（含欠费/余额） | POST | `/iwater/v1/watermeter/queryUserMeterList/v1.json` |
| 抄表信息（上期/本期读数） | POST | `/iwater/v1/watermeter/getMeterInfoByUId/v1.json` |
| 户号查询（绑定前） | POST | `/iwater/v1/watermeter/searchMeterInfoByUId/v1.json` |
| 绑定户号 | POST | `/iwater/v1/watermeter/addMeter/v2.json` |
| 校验短信验证码 | POST | `/iwater/v1/watermeter/checkPhoneCode/v1.json` |
| 账单/用水记录 | POST | `/iwater/v1/watermeter/queryPayMentInfo/v2.json` |
| 行水记录（年度） | POST | `/iwater/memeterinfo/getHangShuiRecord.json` |
| 欠费明细 | POST | `/iwater/v1/watermeter/queryBillPayInfo.json` |

这些路径均已用真实请求验证过存在性（GET 返回 `405 Method Not Allowed`，即确认只接受 POST）
以及响应信封结构。

### 独立客户端

`custom_components/zswater/zswater_client/` 不依赖 Home Assistant，可单独使用，
用法见 `zswater_client_demo.py`：

```bash
python custom_components/zswater/zswater_client_demo.py \
    --mobile 13800000000 --password '你的密码' \
    --captcha-image captcha.png
# 打开 captcha.png 读出验证码后再执行：
python custom_components/zswater/zswater_client_demo.py \
    --mobile 13800000000 --password '你的密码' \
    --captcha 1234 --timestamp 1700000000000
```

### 数据更新策略

- 抄表读数按月更新，默认 6 小时轮询一次足够
- 欠费金额在缴费后会立即变化，如需更快可在「参数设置」里调小刷新间隔
- 需要强制刷新时，重载集成即可

---

## 已知限制

- **不支持仅用短信验证码登录**：营业厅本身没有这个能力（详见上文登录方式第 3 节）
- **不支持自动重新登录**：登录态失效后需要在集成页面手动重新登录（HA 会弹出「重新认证」提示）
- **只做数据抓取，不做任何计算**：不代扣、不缴费、不修改任何账单
- 「绑定新户号」依赖营业厅的短信验证环节；若失败，请先在官方渠道绑定，再用「添加已绑定的户号」
- 若营业厅前端改版，接口路径与字段可能变化，需要在 `zswater_client/const.py` 与
  `zswater_client/models.py` 中同步更新

---

## 免责声明

- **本项目为非官方第三方项目**，与中山公用水务投资有限公司及其关联企业无任何隶属、合作、授权或认可关系（详见顶部[非官方声明](#-非官方声明unofficial)）
- 本项目为个人学习与自用目的编写，作者不对数据准确性、完整性、时效性、可用性作任何保证
- 所有数据以官方营业厅为准；因数据差异导致的任何决策后果，作者不承担责任
- 请仅查询你自己名下的户号，不要用于任何批量抓取、转售或商业用途
- 使用本项目所产生的一切后果由使用者自行承担

## 致谢

- [windyboy/china_southern_power_grid_stat](https://github.com/windyboy/china_southern_power_grid_stat) —— 集成架构参考
- [CubicPill/china_southern_power_grid_stat](https://github.com/CubicPill/china_southern_power_grid_stat) —— 更早的原项目
- [瀚思彼岸论坛](https://bbs.hassbian.com/) 相关帖子的思路启发

## License

[MIT](LICENSE)
