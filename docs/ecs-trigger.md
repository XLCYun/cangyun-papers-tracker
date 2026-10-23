# ECS 每日触发器

ECS 负责计时、检查和调用 GitHub 的 `workflow_dispatch`；采集、翻译、打标、Git 备份与 OSS 发布继续由 `.github/workflows/daily.yml` 执行。该工作流没有 `schedule`，保留手动入口。

## 时间与重试

- 显式使用 `Asia/Shanghai`，每天 13:30 首次检查，之后每 15 分钟检查一次，至 20:45。`Persistent=true` 允许服务器恢复后补做漏过的检查；窗口外不采集，不回填历史日期。
- 当日 OSS 索引和每日 JSON 的日期、篇数与 SHA-256 一致时记为完成；零篇也有效。完成状态缓存在 ECS，后续检查直接退出。
- 发现本工作流的 `main` 运行仍在排队或执行时，等待下一次检查，不再触发第二次采集。
- 没有成功归档或在途任务时才发出 POST。同日最多 3 次，至少间隔 15 分钟。POST 前原子保存次数，网络超时也计次，避免不确定请求导致无限重试。既有采集器仍会复用已归档的成功译文和标签。
- OSS、GitHub 的读取错误、无效状态和哈希错误均报错，不当作“当日缺失”继续 POST。只有真正成功发布才标记完成。翻译或打标回退已发布的日报按完成处理，不因此自动重新调用模型。
- 文件锁防止并发检查；systemd oneshot 的单次运行上限为 120 秒。触发器不等待整份日报处理结束，下一次检查会核实结果。

## 凭证

创建一个专用的 [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new?name=cangyun-arxiv-ecs&target_name=XLCYun&expires_in=90&actions=write)：

1. Resource owner：`XLCYun`。
2. Repository access：`Only select repositories`，仅选择 `cangyun-papers-tracker`。
3. Repository permissions：仅 `Actions: Read and write`，以及 GitHub 自动附带的 `Metadata: Read`。不增加 Contents、Workflows、账户或组织权限。
4. 设置合理的到期时间，在到期前轮换。Token 到期或撤销会导致触发失败，错误可在服务日志中查看。

Actions 写权限也能管理该仓库的运行，例如取消运行；它不是仅对一个工作流授予的独立“触发权限”。仓库限制和权限选择需要在生成页面核对。公开仓库的只读访问属于 GitHub 细粒度 Token 的固有行为。

Token 只写入 ECS 的 `/etc/cangyun-papers-trigger/github-token`，目录为 root `0700`，文件为 root `0600`，不要写入 shell 历史、仓库、网页、命令参数或日志。触发器拒绝 classic Token；普通路径的凭证文件仅接受 `0400` 或 `0600`。

服务通过 systemd `LoadCredential` 将凭证以只读文件交给临时非特权用户，运行状态保存在独立的 `/var/lib/cangyun-papers-trigger`。翻译和 OSS 密钥继续保留在 GitHub Secrets，ECS 触发器不需要这些密钥。

systemd 的运行时凭证副本可能通过 ACL 授权，权限掩码显示为 `0440`。触发器只在 systemd 提供的 `CREDENTIALS_DIRECTORY` 内接受这种只读副本；ECS 上的原始凭证仍保持 root `0600`，普通路径的组可读文件仍会被拒绝。

## 安装与验收

远端需要 Python 3.12+、systemd 和已同步的系统时钟。以下文件部署到 root 管理的独立路径：

| 仓库文件 | ECS 路径 |
| --- | --- |
| `scripts/trigger-arxiv-daily.py` | `/opt/cangyun-papers-trigger/trigger-arxiv-daily.py` |
| `deploy/systemd/cangyun-arxiv-daily.service` | `/etc/systemd/system/cangyun-arxiv-daily.service` |
| `deploy/systemd/cangyun-arxiv-daily.timer` | `/etc/systemd/system/cangyun-arxiv-daily.timer` |

代码与 unit 文件均使用 root `0644`，代码目录为 `0755`。写入凭证后，先校验并加载 unit：

```sh
systemd-analyze verify /etc/systemd/system/cangyun-arxiv-daily.service /etc/systemd/system/cangyun-arxiv-daily.timer
systemctl daemon-reload
python3 /opt/cangyun-papers-trigger/trigger-arxiv-daily.py --probe
```

`--probe` 真正调用 GitHub，但仅触发 `verify_only=true` 的权限探针。确认 Actions 中出现成功的 **ECS trigger verification**，且 `collect`、`publish` 跳过后，再启用 timer：

```sh
systemctl enable --now cangyun-arxiv-daily.timer
systemctl start cangyun-arxiv-daily.service
systemctl list-timers cangyun-arxiv-daily.timer --all --no-pager
journalctl -u cangyun-arxiv-daily.service -n 20 --no-pager
```

正常日志只有状态、日报日期、篇数、尝试次数和可用的运行链接，不打印 Token、请求头或上游响应正文。认证请求不跟随重定向、不使用环境代理；认证 API 只允许 `api.github.com`，回环 HTTP 仅供离线测试。

## 故障恢复与回退

用 `journalctl` 检查 ECS 检查结果，再检查 GitHub 的实际运行和 OSS 索引。认证失败时更新专用 Token 并重新运行权限探针，不扩大权限。达到当日 3 次上限后由管理员查明失败原因，再通过 GitHub 手动重跑；不删除状态来反复计费。正常的下一天会自动重置当日计数。

停止 ECS 调度用 `systemctl disable --now cangyun-arxiv-daily.timer`；这不会取消已有的 GitHub 运行。若要恢复 GitHub cron，先停 ECS timer，再将所需 `schedule` 作为代码变更提交到 `main`，避免两个调度入口同时生效。不要禁用整个 Daily arXiv 工作流，手动入口与 ECS 都需要它。

本地验证：

```sh
uv run --locked pytest tests/test_daily_trigger.py
```

测试以本地 HTTP 固定响应覆盖外部 API、时间和凭证边界，不调用真实模型、不操作云资源。
