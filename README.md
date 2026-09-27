# 社保缴费清单上送台

经办人导入大批量社保缴费记录，系统自动校验（身份证号 / 缴费月份 / 金额 / 单位编号），
校验通过后分批提交至外部平台，异常结果实时回写任务；支持超时批次重试与错误明细下载。

## 功能特性

| 功能 | 说明 |
| --- | --- |
| 清单导入 | CSV 上传（UTF-8/GBK 自动识别，中英文表头），单任务最大 20 万行 |
| 记录校验 | 身份证校验位（GB 11643-1999）、月份格式与范围、金额精度与上下限、单位编号登记核验、任务内同人同月查重 |
| 分批提交 | 默认 100 条/批，信号量限流并发提交，结果逐条回写 |
| 超时处理 | 调用外部平台超时 → 批次与记录置为 TIMEOUT，等待经办人重试 |
| 批次重试 | 超时/失败批次一键重试，仅重发批内未成功记录；幂等键防重复入账 |
| 错误明细 | 校验错误 + 提交失败 + 超时记录导出 CSV（带 BOM，Excel 直接打开） |
| 单位管理 | 缴费单位登记维护，校验时实时核验 |

## 快速开始

```bash
pip install -r requirements.txt

# 启动服务（默认 8000 端口）
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 打开操作台
open http://localhost:8000
```

生成演示数据（1000 行，含约 10% 异常 + 1 对重复）：

```bash
python3 scripts/gen_sample.py --rows 1000 --out sample_data.csv
```

运行测试：

```bash
python3 -m pytest tests/ -q
```

## 业务流程

```
上传CSV ──► 创建任务(PENDING) ──► 后台校验(VALIDATING) ──► 待提交(VALIDATED)
                                                              │ 经办人点击提交
                                                              ▼
                              分批(100条/批)并发提交外部平台(SUBMITTING)
                                                              │
              ┌───────────────┬──────────────────┬───────────┘
              ▼               ▼                  ▼
         批次全部成功      批次部分/全部失败      批次超时(TIMEOUT)
              │               │                  │
              │               │                  └──► 经办人重试 ──► 重新提交批内未成功记录
              ▼               ▼                  ▼
                          任务完成(COMPLETED)，统计实时回写
                                                              │
                                          错误明细(校验错误/提交失败/超时) CSV 下载
```

## 校验规则

| 字段 | 规则 |
| --- | --- |
| 身份证号 | 18 位；前 17 位数字 + 末位数字或 X；出生日期合法且不晚于当前日期；GB 11643-1999 校验位 |
| 缴费月份 | `YYYY-MM` 格式；范围 2000-01 至当前月 |
| 缴费金额 | 0.01 ~ 999999.99，最多两位小数 |
| 单位编号 | 必须已在「缴费单位管理」中登记 |
| 其他 | 姓名非空且 ≤64 字符；同一任务内同人同月判重 |

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/tasks/upload` | 上传清单 CSV，自动触发校验 |
| GET | `/api/tasks` | 任务列表（状态筛选、分页） |
| GET | `/api/tasks/{id}` | 任务详情与统计 |
| GET | `/api/tasks/{id}/records` | 记录列表（状态筛选、分页） |
| GET | `/api/tasks/{id}/batches` | 批次列表 |
| POST | `/api/tasks/{id}/submit` | 触发分批提交（异步） |
| POST | `/api/batches/{id}/retry` | 重试超时/失败批次 |
| GET | `/api/tasks/{id}/errors/download` | 下载错误明细 CSV |
| GET | `/api/sample-csv` | 下载 CSV 模板 |
| GET/POST/DELETE | `/api/units` | 缴费单位管理 |

## 设计要点

- **幂等防重**：每条上送记录携带 `idempotency_key = 批次号:记录ID`，外部平台据此去重，
  超时重试不会产生重复入账（模拟客户端 `SimulatedExternalClient` 已实现该语义）。
- **重试语义**：仅 `TIMEOUT / FAILED / PARTIAL_FAILED` 状态的批次可重试；
  重试只重发批内状态为 `TIMEOUT / FAILED` 的记录，已成功记录不受影响。
- **分批与限流**：默认 100 条/批、3 批次并发（`submit_service.DEFAULT_*` 可调），
  每批独立数据库会话，单批失败不影响其他批次。
- **统计回写**：每批完成后按记录状态实时重算任务统计（成功/失败/超时），
  前端 3 秒轮询展示进度。
- **外部平台适配**：`app/services/external_client.py` 中的 `SimulatedExternalClient`
  为模拟实现；接入真实平台时实现相同的 `submit_batch(batch_no, records)` 契约即可，
  无需改动业务流程代码。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SIP_DB_PATH` | `./sip.db` | SQLite 数据库路径 |
| `SIP_EXT_LATENCY` | `0.3` | 模拟外部平台响应延迟（秒） |
| `SIP_EXT_FAIL_RATE` | `0.08` | 模拟记录级拒绝率 |
| `SIP_EXT_TIMEOUT_RATE` | `0.10` | 模拟批次超时率 |
| `SIP_SYNC` | - | `1` 时后台任务同步执行（测试用） |

## 目录结构

```
app/
├── main.py                 # 应用入口（FastAPI 装配、启动种子数据）
├── database.py             # SQLite 引擎与会话（WAL、busy_timeout）
├── models.py               # Task / PaymentRecord / Batch / Unit
├── validators.py           # 身份证/月份/金额/单位校验规则
├── seed.py                 # 预置缴费单位
├── services/
│   ├── import_service.py   # CSV 解析、任务创建、批量校验
│   ├── submit_service.py   # 分批提交、超时处理、批次重试、统计回写
│   ├── external_client.py  # 外部平台客户端（模拟，含幂等/超时语义）
│   └── runner.py           # 后台任务执行器（异步/同步可切换）
├── routers/
│   ├── tasks.py            # 任务/记录/批次/错误下载 API
│   └── units.py            # 单位管理 API
└── static/index.html       # 操作台前端（原生 JS，3s 轮询）
scripts/gen_sample.py       # 演示数据生成器
tests/                      # 46 个测试：校验规则/导入/提交/重试/下载/单位
```
