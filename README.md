# 社保缴费清单上送台

经办人导入大批量缴费记录，系统校验身份证号、月份、金额、单位编号，通过后分批上送外部平台，
异常结果回写任务，支持重试超时批次与下载错误明细。**纯 Python 标准库实现，零第三方依赖。**

## 快速开始

```bash
./run.sh                        # 启动主服务(8080) + 模拟外部平台(9100)
python3 scripts/gen_sample.py data/sample.csv 1000   # 生成1000条测试数据(含各类异常)
```

浏览器打开 http://127.0.0.1:8080 ，或用 API 操作：

```bash
# 1.导入任务
curl -X POST http://127.0.0.1:8080/api/tasks -F "name=9月上送" -F "file=@data/sample.csv"
# 2.校验
curl -X POST http://127.0.0.1:8080/api/tasks/1/validate
# 3.分批上送(后台异步, 每批100条, 3线程并发)
curl -X POST http://127.0.0.1:8080/api/tasks/1/submit
# 4.查看批次 / 重试超时批次
curl http://127.0.0.1:8080/api/tasks/1/batches
curl -X POST http://127.0.0.1:8080/api/batches/{批次ID}/retry
# 5.下载错误明细
curl -OJ http://127.0.0.1:8080/api/tasks/1/errors.csv
```

## 处理流程

```
导入CSV ──> IMPORTED ──校验──> VALIDATED ──上送──> SUBMITTING ──> DONE
              任务               │记录: VALID/INVALID + 错误原因
                                 └> 有效记录按100条分批
批次: PENDING → SUBMITTING → SUCCESS / PARTIAL / FAILED / TIMEOUT ──重试──> 重新上送(≤3次)
记录: PENDING → SUCCESS / FAILED(平台拒绝原因逐条回写)
任务: 成功数/失败数/超时批次数 实时汇总回写
```

## 校验规则

| 字段 | 规则 |
|---|---|
| 身份证号 | 18位、出生日期合法、GB11643 校验位（15位提示升级） |
| 缴费月份 | YYYYMM、01-12、不晚于当前月、不早于202001 |
| 缴费金额 | 数字、>0、最多两位小数、≤999999.99 |
| 单位编号 | 6-12位字母数字，且须存在于单位表（内置10家单位） |

## 关键设计

- **分批上送**：有效记录按 `BATCH_SIZE`(默认100) 分批，后台线程池并发提交，不阻塞页面。
- **超时判定**：平台响应超过 `PLATFORM_TIMEOUT`(默认2s) 记为 TIMEOUT 批次。
- **重试**：仅 TIMEOUT/FAILED 批次可重试，最多 `MAX_RETRY`(默认3) 次；以数据库批次ID作
  幂等键，平台重复提交返回原结果，避免重复入账。
- **结果回写**：平台逐条返回结果 → 记录级 `submit_status/submit_error`；批次级状态/平台批次号；
  任务级成功/失败/超时批次汇总。
- **错误明细**：校验失败 + 上送失败合并导出 CSV（带 BOM，Excel 直接打开）。

## 目录结构

```
app/config.py           配置(批次大小/超时/重试次数/端口)
app/db.py               SQLite 数据层(tasks/records/batches/units)
app/validator.py        四类字段校验
app/platform_client.py  外部平台HTTP客户端(超时控制)
app/service.py          业务逻辑(导入/校验/上送/回写/重试/错误明细)
app/server.py           主服务 HTTP API + 静态页面
app/mock_platform.py    模拟外部平台(延迟/超时/拒绝/幂等)
static/index.html       Web 操作界面
scripts/gen_sample.py   测试数据生成器
```

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/tasks | 导入CSV创建任务(multipart: name, file) |
| GET | /api/tasks | 任务列表 |
| GET | /api/tasks/{id} | 任务详情(含汇总计数) |
| POST | /api/tasks/{id}/validate | 执行校验 |
| POST | /api/tasks/{id}/submit | 分批上送 |
| GET | /api/tasks/{id}/records?status=&page= | 记录明细(status: invalid/failed/success/valid) |
| GET | /api/tasks/{id}/batches | 批次列表 |
| POST | /api/batches/{id}/retry | 重试超时/失败批次 |
| GET | /api/tasks/{id}/errors.csv | 下载错误明细 |
| GET | /api/units | 单位编号表 |

真实平台接入：设置环境变量 `PLATFORM_URL` 指向实际上送地址即可替换模拟平台。
