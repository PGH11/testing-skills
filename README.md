# Testing Skills

测试领域技能沉淀与自动化脚本集合，包含 Web 自动化、SEO 测试、性能测试、多语言测试等实战工具。

## 📁 目录结构

```
testing-skills/
├── scripts/          # Python 自动化脚本
└── docs/             # 测试方法与 SOP 文档
```

## 📜 脚本说明 (scripts/)

| 文件名 | 说明 |
|--------|------|
| `check_urls_violations.py` | 基于 Playwright 的多语言 URL 违规内容检查脚本，支持多线程并发扫描 |
| `extract_sitemap_urls.py` | 从 sitemap.xml 提取所有 URL 并导出为 JSON，支持多语言站点 |
| `gugelogin.py` | Google Search Console 自动登录脚本，保存/注入登录态避免重复登录 |
| `冷启动性能测试脚本.py` | Web 页面冷启动性能测试，自动收集 Performance API 指标 |

## 📚 文档说明 (docs/)

| 文件名 | 说明 |
|--------|------|
| `多语言测试.md` | 多语言分层测试思路与自动化校验方案总结 |
| `SKILL_TEST_GUIDE_FORUM.md` | Skill 自动化测试实战总结，三层分治测试架构 |
| `Screaming Frog 工具配置 SOP（nuxt框架）.md` | SEO 抓取工具 Screaming Frog 配置标准操作流程 |
| `Fiddler + MuMu 模拟器抓取 Android 应用SOP文档.docx` | Fiddler 抓包安卓模拟器完整步骤 |

## 📝 License

个人技能沉淀，仅供参考学习。
