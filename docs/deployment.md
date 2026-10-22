# 研究站部署与回退

站点代码部署到 ECS 的独立目录 `/var/www/cangyun-papers-tracker`。日报 JSON 由每日工作流直接发布到 OSS，更新日报不需要重新部署网页。既有 Benchmark 文件继续使用原 OSS 地址。

## 构建并发布静态文件

本机需要 Node.js、Python 3.12+、rsync，以及配置好的 ECS SSH 别名。远端需要 Python 3、rsync 和 Nginx。SSH 账户须能写入研究站目录。

在待发布提交的干净检出中执行：

```sh
npm ci
npm test
uv run --locked pytest
npm run build

RESEARCH_HOST=your-ecs-ssh-alias
RESEARCH_RELEASE=$(git rev-parse --short=12 HEAD)
python3 scripts/deploy-site.py deploy --host "$RESEARCH_HOST" --release "$RESEARCH_RELEASE" --dist dist
```

命令只上传 `dist/`。它先检查静态文件类型，拒绝隐藏文件、软链、PDF 和源代码目录；随后上传到独立临时目录，逐文件比对 SHA-256，校验成功才将其保存为 `releases/<release>` 并原子切换 `current` 软链。相同名称的版本只有内容完全一致时才会复用，上一版保存在 `previous`，上传或校验失败不切换当前版本。旧版本不会自动删除。

标准输出是 JSON 回执，包含当前版本、上一版、文件数和字节数。将实际发布回执、云资源变更回执、Nginx 配置备份和验证截图保存在仓库外。不要提交真实环境文件、密钥或账户配置。`--base` 仅用于另一个明确隔离的部署目录；生产环境沿用默认目录。

## 首次配置 DNS、Nginx 和 HTTPS

这些是管理员的一次性操作，不由每日工作流执行。

1. 查询 `cyunlab.com` 的 DNS 记录。`research` 没有记录时添加指向 ECS 公网 IP 的 A 记录；已有相同记录直接复用，值不同则先确认归属。不要改官网记录。
2. 将 `deploy/nginx/cangyun-research-static.conf` 安装为 `/etc/nginx/snippets/cangyun-research-static.conf`。将 `research-http.conf` 安装为 `/etc/nginx/sites-available/cangyun-papers-tracker`，并在 `sites-enabled/` 建立相应软链。保留其他站点配置。
3. 创建 `/var/www/letsencrypt`；运行 `nginx -t`，成功后才 reload。确认公网 DNS 和该域名的 HTTP ACME challenge 路径可达。
4. 使用服务器已有 ACME 账户申请独立证书：

   ```sh
   certbot certonly --webroot -w /var/www/letsencrypt --cert-name research.cyunlab.com -d research.cyunlab.com --non-interactive
   ```

5. 将 `research-https.conf` 替换到新站的 `sites-available` 文件，再次 `nginx -t`，成功后 reload。模板使用研究站独立证书，复用服务器已有的 Certbot TLS 参数文件。
6. 将 `deploy/certbot/reload-research-nginx.sh` 以 `0755` 权限安装至 `/etc/letsencrypt/renewal-hooks/deploy/reload-research-nginx.sh`。先用 `sh -n` 检查脚本语法。该钩子只在 `RENEWED_LINEAGE` 为 `/etc/letsencrypt/live/research.cyunlab.com` 时执行 `nginx -t`，检查成功才 reload Nginx；其他证书续期不执行操作。确认自动续期 timer 正常，研究站证书的续期配置仍使用 `/var/www/letsencrypt`。

HTTPS 模板保留 HTTP ACME 路径，其余 HTTP 请求跳到研究站 HTTPS。三个页面路径都由 SPA 处理；入口 HTML 重新验证缓存，带内容哈希的资源长期缓存，缺失的资源返回 404。

## OSS CORS

前端直接读取 `https://updates.cyunlab.com/research/arxiv-daily/`。管理员先将完整 CORS 配置备份到仓库外，再将 `https://research.cyunlab.com` 加入既有 GET/HEAD 规则，保留官网来源和其他字段，并启用 `ResponseVary`。`PutBucketCors` 会替换整个配置，不能只写一条新规则。

Bucket 继续保持 private；新日报 JSON 使用对象级 `public-read`。每日 Actions 的 RAM 用户只具有 `research/arxiv-daily/*` 的 PutObject/GetObject 权限，不授予 CORS、Bucket ACL、列表或删除权限。不要调整既有 Benchmark 对象。

## 发布验收

真实发布后检查下列公开接口；网络或解析失败不能记为零篇日报。

- `https://research.cyunlab.com/`、`/arxiv-daily`、`/enterprise-agent-benchmark` 均可直接打开、刷新，并有正确的独立 TLS 证书。
- HTML 为 `no-cache`，抽查构建中的带哈希资源为 `immutable`，不存在的 `/assets/missing.js` 返回 404。
- OSS `index.json` 与当日不可变 JSON 可匿名读取，日报字节的 SHA-256 与索引一致；分别以研究站和官网 Origin 请求，检查对应的 `Access-Control-Allow-Origin` 和 `Vary: Origin`。
- 桌面和手机浏览器核对每日日期切换、搜索与英文回退；Benchmark 仍为 101 项、九标签，保留 74 项公共资产与 27 项 source-only，卡片互斥展开。

新站通过后才移除官网的研究入口及两条旧研究路径。官网 Nginx 中原研究路径的重定向也须撤掉，让旧路径明确返回 404；官网云景首页和现有产品规则继续使用原配置。

## 回退

恢复上一版研究站：

```sh
python3 scripts/deploy-site.py rollback --host "$RESEARCH_HOST"
```

命令验证两个版本软链都位于本站 `releases/` 中，再原子恢复上一版，并交换 `current` 与 `previous`，便于重新切回。首次部署没有上一版时会报错，当前站点不受影响。切换静态版本通常不需要 reload Nginx。

如果回退整个迁移，先恢复官网原研究路由及原发布目录，再恢复研究站配置和版本。Nginx 配置回退仍须先 `nginx -t`。不要删除已公开的 OSS JSON、论文对象或原站发布目录；DNS 和证书的撤销属于独立管理员操作。
