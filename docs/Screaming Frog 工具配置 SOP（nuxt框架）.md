# Screaming Frog 工具配置 SOP（nuxt框架）

> 目标：让抓取结果尽量贴近搜索引擎视角，并确保结构化数据/静态资源等可被正确提取与导出证据。

## 1. 抓取模式怎么选

- **全站体检（Spider）**：用于系统扫描整个站点；输入站点入口 URL 后沿站内链接爬行。

- **新增页面验收（List）**：最推荐的回归方式；把待验收 URL 清单逐行导入，只抓这批 URL，结果更干净。

## 2. 渲染口径（Text Only vs JavaScript）

- **Text Only**（更像 view-source）：速度快，适合 SSR/静态站；但若页面依赖 JS 注入 title/H1/正文/Schema，会被误判缺失。

- **JavaScript**（更像真实浏览器）：更接近实际渲染结果，但更慢；用于判定 client-only/异步加载导致的可抓取性问题。

- 配置入口：`Configuration > Spider > Rendering`

- ![](C:\Users\pangguohao\AppData\Roaming\marktext\images\2026-02-09-16-59-57-image.png)

推荐实践（两轮对比）：

- 第一轮：Text Only 快速扫明显错误（title/description/canonical/状态码等）。

- 第二轮：用 JavaScript Rendering 复核并导出证据对比。

## 3. 必开：结构化数据提取（Schema）

如果你要检查 Schema.org（JSON-LD/Microdata/RDFa），必须开启提取：

- 入口：`Configuration > Spider > Extraction`

- 勾选：`Extract Structured Data`，并启用 **JSON-LD / Microdata / RDFa**（按站点实际使用选择）。

- ![](C:\Users\pangguohao\AppData\Roaming\marktext\images\2026-02-09-17-01-02-image.png)

验证是否生效：抓 1 个你确定有 Schema 的 URL，查看 `Structured Data` Tab 是否出现 `Types`。

## 4. 必开：抓取静态资源（发现 JS/CSS/图片/字体 404）

- 入口：`Configuration > Spider > Crawl`

- 勾选：`Crawl Linked Resources`，并确保 Images/CSS/JavaScript 都在 Crawl 范围内。

- ![](C:\Users\pangguohao\AppData\Roaming\marktext\images\2026-02-09-17-02-55-image.png)

## 5. Robots 与 User-Agent（尽量贴近真实抓取）

- **Robots**：默认建议 `Respect robots.txt`（更贴近搜索引擎）。在测试/预发若 robots 全禁可临时关闭。

- ![](C:\Users\pangguohao\AppData\Roaming\marktext\images\2026-02-09-17-04-17-image.png)

- **User-Agent**：建议至少跑一轮 `Googlebot Smartphone`；复核交互/渲染问题时可用 `Chrome` + JS Rendering。

- ![](C:\Users\pangguohao\AppData\Roaming\marktext\images\2026-02-09-17-03-56-image.png)

## 6. 速度限制

- 入口：`Configuration > Speed`

- 建议保守值：Threads=3~5，URLs/s=1~2，Timeout=20~30s（按站点承载能力调整）。

## 7. Sitemap / URL 输入建议

- 检查 sitemap 本身：直接用 `List` 模式导入 sitemap URL（例如 `/sitemap.xml`、`/sitemap-video.xml`），查看 Response Codes 与解析情况。

- 只验收新增页面：`List` 模式导入 URL 清单（每行一个）。

## 8. 导出

- 每个问题项建议导出：命中 URL 列表（含 Status Code）、必要时附上 `Inlinks`（定位来源页）。

- Structured Data 类问题建议导出：Types、Validation Errors/Warnings、以及涉及的 URL 字段（必要时做二次抓取验证）。
