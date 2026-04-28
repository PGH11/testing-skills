from playwright.sync_api import sync_playwright
import time
import json
import os

class WebPerformanceTest:
    def __init__(self, url):
        self.url = url
        self.performance_metrics = {}
        self.web_vitals = {}

    def run_test(self):
        """执行性能测试"""
        with sync_playwright() as p:
            # 启动浏览器，禁用缓存和GPU着色器缓存以确保干净测试环境
            browser = p.chromium.launch(
                # 建议在生产环境设置为 True，这里保留 False 以方便观察
                headless=False,
                args=[
                    "--disable-cache",
                    "--disable-application-cache",
                    "--disable-offline-load-stale-cache",
                    "--disable-gpu-shader-disk-cache",
                ],
            )

            # 配置上下文：禁用缓存、大视口、忽略HTTPS错误
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                # 只有需要时才开启视频录制
                # record_video_dir="./videos/" 
                ignore_https_errors=True,
                java_script_enabled=True,
                # 禁用缓存
                extra_http_headers={"Cache-Control": "no-cache"},
            )

            # 清除浏览器状态
            context.clear_cookies()
            context.clear_permissions()
            page = context.new_page()

            try:
                # 启用性能指标收集 (必须在 goto 之前注入)
                self._enable_performance_tracking(page)

                # 导航到目标URL
                start_time = time.time()
                # 导航，等待 DOMContentLoaded，超时 60s
                page.goto(self.url, wait_until="domcontentloaded", timeout=60000)
                navigation_time = time.time() - start_time

                # 智能等待：等待页面所有资源（包括图片、样式等）加载完成
                # 确保 FCP/LCP 等指标稳定
                print("等待页面 Load 状态...")
                try:
                    # 增加超时时间到30秒，应对加载大量资源的页面
                    page.wait_for_load_state("load", timeout=30000)
                    print("页面 Load 状态已完成")
                except Exception as e:
                    # 如果 Load 状态超时，使用网络空闲和固定等待作为备选策略
                    print(f"等待 Load 状态超时，使用备选策略: {e}")
                    # 等待网络空闲状态（最多10秒）
                    print("等待网络空闲状态...")
                    page.wait_for_load_state("networkidle", timeout=10000)
                    # 再等待2秒确保指标稳定
                    page.wait_for_timeout(2000)

                # 检测并关闭可能出现的弹窗
                self._handle_popups(page)

                # 模拟用户交互（包含滚动和点击，以触发 INP 和 CLS）
                self._simulate_user_interactions(page)

                # 智能等待：等待网络活动空闲，确保所有 Web Vitals 指标，尤其是 LCP 和 INP 的最终值被捕获
                print("等待网络空闲（Network Idle）以稳定 Web Vitals 指标...")
                page.wait_for_load_state("networkidle", timeout=10000)

                # 获取性能指标
                self._get_performance_metrics(page)
                self._get_web_vitals(page)
                self._get_resources_info(page)

                # 添加导航时间
                self.performance_metrics["navigation_time"] = round(navigation_time * 1000, 2)

                # 输出测试结果
                self._print_results()

                # 保存结果到文件
                self._save_results()

            finally:
                # 关闭浏览器
                page.close()
                context.close()
                browser.close()

    def _enable_performance_tracking(self, page):
        """启用性能跟踪"""
        web_vitals_script = """
        window.webVitals = {
            fcp: null,
            lcp: null,
            cls: 0, // CLS 初始化为 0
            cls_with_input: 0,
            inp: 0,
            ttfb: null
        };

        // 监听 TTFB (确保在 PerformanceObserver 之前获取)
        const navEntry = performance.getEntriesByType('navigation')[0];
        if (navEntry) {
            window.webVitals.ttfb = navEntry.responseStart;
        }

        // 监听 FCP - 使用 PerformanceObserver 确保准确捕获
        new PerformanceObserver((list) => {
            const fcpEntry = list.getEntriesByName('first-contentful-paint')[0];
            if (fcpEntry) {
                window.webVitals.fcp = fcpEntry.startTime;
            }
        }).observe({ type: 'paint', buffered: true });

        // 监听 LCP - 持续监听并更新为最新值
        new PerformanceObserver((list) => {
            const entries = list.getEntries();
            const lcpEntry = entries[entries.length - 1]; // 始终取最新的LCP条目
            if (lcpEntry) {
                window.webVitals.lcp = lcpEntry.startTime;
            }
        }).observe({ type: 'largest-contentful-paint', buffered: true });

        // 监听 CLS - 累加布局偏移，严格区分是否有用户输入
        new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
                window.webVitals.cls_with_input += entry.value; // 始终累加
                if (!entry.hadRecentInput) {
                    window.webVitals.cls += entry.value; // 官方 CLS (不包含最近输入)
                }
                // 确保 CLS 值始终被更新
                window.webVitals.cls = parseFloat(window.webVitals.cls.toFixed(4));
                window.webVitals.cls_with_input = parseFloat(window.webVitals.cls_with_input.toFixed(4));
            }
        }).observe({ type: 'layout-shift', buffered: true });

        // 监听 INP - 计算最长的交互延迟
        let maxInp = 0;
        new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
                // INP 衡量处理时间，使用 processingEnd - startTime
                // 排除持续性事件 (如 wheel, scroll)，虽然 PerformanceObserver 的 event 类型会倾向于离散事件
                if (['click', 'mousedown', 'keydown'].includes(entry.name)) {
                    const latency = (entry.processingEnd || entry.responseEnd) - entry.startTime;
                    if (latency > maxInp) {
                        maxInp = latency;
                        window.webVitals.inp = maxInp;
                    }
                }
            }
        }).observe({ type: 'event', buffered: true });
        """
        page.add_init_script(web_vitals_script)

    def _handle_popups(self, page):
        """检测并关闭可能出现的弹窗。"""
        # ... (此处省略原有的 _handle_popups 方法，因为它已相对完整) ...
        try:
            print("开始检测和关闭弹窗...")
            # 常见的弹窗关闭按钮选择器列表
            close_button_selectors = [
                ".close", ".popup-close", ".modal-close", ".overlay-close",
                ".close-btn", ".close-button", ".dismiss", ".dismiss-btn",
                "[class*='close']", "[class*='popup'] [class*='close']",
                "button[aria-label*='close']", "button[title*='close']",
                "[aria-label*='关闭']", "[title*='关闭']",
                ".popup .close", ".modal .close",
                "button:has(svg) [d*='M'], button:has(path) [d*='M']",
                "[class*='icon-close']", "[class*='x-button']",
                "#close", "#popup-close", "#modal-close"
            ]

            # 尝试点击每个选择器，直到找到并关闭弹窗
            for selector in close_button_selectors:
                try:
                    # 检查元素是否存在且可见
                    if page.locator(selector).is_visible(timeout=500):
                        print(f"找到弹窗，使用选择器关闭: {selector}")
                        # 点击关闭按钮，确保不触发导航
                        page.locator(selector).click(timeout=1000)
                        page.wait_for_timeout(500)  # 等待弹窗关闭动画完成
                        break
                except Exception:
                    # 忽略单个选择器的错误，继续尝试下一个
                    continue
            
            # 额外检查是否有覆盖层或弹窗容器，尝试移除
            popup_containers = [
                ".popup", ".modal", ".overlay", ".lightbox",
                ".newsletter-popup", ".cookie-popup",
                ".promo-popup", ".welcome-popup"
            ]
            
            for container in popup_containers:
                try:
                    if page.locator(container).is_visible(timeout=500):
                        print(f"找到弹窗容器，尝试隐藏: {container}")
                        # 使用JavaScript隐藏弹窗，避免触发跳转
                        page.evaluate(f"document.querySelector('{container}').style.display = 'none'")
                        page.wait_for_timeout(500)
                        break
                except Exception:
                    continue
            
            print("弹窗检测和关闭完成")
        
        except Exception as e:
            # 忽略弹窗处理过程中的所有错误，确保测试继续执行
            print(f"弹窗处理过程中发生错误: {e}")


    def _simulate_user_interactions(self, page):
        """模拟用户交互来触发CLS和INP（包含滚动和点击）"""
        try:
            print("开始模拟用户交互...")
            
            # 1. 滚动交互 (触发 CLS)
            print("执行滚动操作...")
            for i in range(3):
                page.mouse.wheel(0, 500)  # 向下滚动
                page.wait_for_timeout(300)
            
            # 2. 离散点击交互 (触发 INP)
            print("执行离散点击操作以触发INP...")
            try:
                # 尝试点击一个常见的可交互元素（按钮、链接等）
                # 提高优先级，选择第一个可见的通用可点击元素
                page.locator("button, a[role='button'], input[type='submit'], [aria-label]").first.click(timeout=1000)
                page.wait_for_timeout(500)
            except Exception:
                # 如果找不到，尝试点击页面中心
                print("未找到特定按钮，尝试点击页面中心。")
                page.mouse.click(page.viewport_size['width'] / 2, page.viewport_size['height'] / 2)
                page.wait_for_timeout(500)
            
            # 3. 再次滚动以确保 CLS 窗口捕获完全
            page.mouse.wheel(0, -500) # 向上滚动
            page.wait_for_timeout(500)
            
            print("用户交互模拟完成。")
        except Exception as e:
            print(f"交互模拟过程中发生错误: {e}")

    # ... (其他方法 _get_performance_metrics, _get_web_vitals, _get_resources_info, _print_results, _save_results 保留不变) ...
    def _get_performance_metrics(self, page):
        """获取性能指标"""
        # 获取Navigation Timing API数据
        navigation_timing = page.evaluate(
            """
            JSON.parse(JSON.stringify(performance.getEntriesByType('navigation')[0]))
        """
        )
        # 提取关键指标
        if navigation_timing:
            self.performance_metrics.update(
                {
                    "ttfb": round(navigation_timing.get("responseStart", 0), 2),
                    "dns_time": round(
                        navigation_timing.get("domainLookupEnd", 0)
                        - navigation_timing.get("domainLookupStart", 0),
                        2,
                    ),
                    "tcp_time": round(
                        navigation_timing.get("connectEnd", 0)
                        - navigation_timing.get("connectStart", 0),
                        2,
                    ),
                    "ssl_time": round(
                        (
                            navigation_timing.get("connectEnd", 0)
                            - navigation_timing.get("secureConnectionStart", 0)
                            if navigation_timing.get("secureConnectionStart", 0) > 0
                            else 0
                        ),
                        2,
                    ),
                    "ttfp": round(navigation_timing.get("responseEnd", 0), 2),
                    "dom_content_loaded": round(
                        navigation_timing.get("domContentLoadedEventEnd", 0)
                        - navigation_timing.get("navigationStart", 0),
                        2,
                    ),
                    "load_time": round(
                        navigation_timing.get("loadEventEnd", 0)
                        - navigation_timing.get("navigationStart", 0),
                        2,
                    ),
                }
            )

    def _get_web_vitals(self, page):
        """获取Web Vitals指标"""
        web_vitals = page.evaluate("window.webVitals")
        # 安全获取Web Vitals值，处理可能的None情况
        self.web_vitals = {
            "fcp": round(web_vitals.get("fcp", 0) or 0, 2),
            "lcp": round(web_vitals.get("lcp", 0) or 0, 2),
            "cls": round(web_vitals.get("cls", 0) or 0, 4),
            "cls_with_input": round(web_vitals.get("cls_with_input", 0) or 0, 4),
            "inp": round(web_vitals.get("inp", 0) or 0, 2),
            "ttfb": round(web_vitals.get("ttfb", 0) or 0, 2),
        }

    def _get_resources_info(self, page):
        """获取资源加载信息"""
        # 获取完整的资源信息，包括URL和类型
        resources = page.evaluate(
            """
            performance.getEntriesByType('resource').map(entry => ({
                name: entry.name,
                type: entry.initiatorType,
                duration: entry.duration,
                size: entry.transferSize || 0,
                entryType: entry.entryType,
                responseEnd: entry.responseEnd
            }))
        """
        )
        # 定义图片扩展名列表，包含webp格式
        image_extensions = [
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".svg",
            ".bmp",
            ".tiff",
        ]
        img_resources = []
        other_resources = []
        all_image_resources = []  # 包含所有图片资源，无论类型
        webp_resources = []  # 专门统计webp格式资源
        for resource in resources:
            # 检查URL是否包含图片扩展名
            url = resource["name"].lower()
            is_image_url = any(url.endswith(ext) for ext in image_extensions)
            is_webp_url = url.endswith(".webp")
            # 收集所有图片资源
            if resource["type"] == "img" or is_image_url:
                all_image_resources.append(resource)
                # 统计webp格式资源
                if is_webp_url:
                    webp_resources.append(resource)
            if resource["type"] == "img":
                img_resources.append(resource)
            elif is_image_url:
                other_resources.append(resource)
        # 统计资源信息
        resource_stats = {
            "total_resources": len(resources),
            "total_size_kb": round(sum(r["size"] for r in resources) / 1024, 2),
            "avg_resource_duration": (
                round(sum(r["duration"] for r in resources) / len(resources), 2)
                if resources
                else 0
            ),
            "total_image_resources": len(all_image_resources),  # 新增：所有图片资源计数
            "webp_resources_count": len(webp_resources),  # 新增：webp格式资源计数
        }
        # 按资源类型统计
        resource_by_type = {}
        for resource in resources:
            # 检查是否为图片资源，用于更准确的统计
            url = resource["name"].lower()
            is_image_url = any(url.endswith(ext) for ext in image_extensions)
            # 使用原始类型进行统计，但同时跟踪所有图片资源
            resource_type = resource["type"]
            if resource_type not in resource_by_type:
                resource_by_type[resource_type] = {
                    "count": 0,
                    "total_size_kb": 0,
                    "avg_duration": 0,
                    "total_duration": 0,
                }
            resource_by_type[resource_type]["count"] += 1
            resource_by_type[resource_type]["total_size_kb"] += round(
                resource["size"] / 1024, 2
            )
            resource_by_type[resource_type]["total_duration"] += resource["duration"]
        # 计算平均值
        for resource_type in resource_by_type:
            resource_by_type[resource_type]["avg_duration"] = round(
                resource_by_type[resource_type]["total_duration"]
                / resource_by_type[resource_type]["count"],
                2,
            )

        resource_stats["by_type"] = resource_by_type

        self.performance_metrics["resource_stats"] = resource_stats

    def _print_results(self):
        """打印测试结果"""

        print("=" * 60)

        print("Web 性能测试报告")

        print(f"测试URL: {self.url}")
        print(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        print("\n[核心 Web Vitals 指标]")
        print(f"├─ FCP (首次内容绘制): {self.web_vitals['fcp']} ms")
        print(f"├─ LCP (最大内容绘制): {self.web_vitals['lcp']} ms")
        print(f"├─ CLS (累积布局偏移): {self.web_vitals['cls']}")
        print(f"├─ CLS(包含交互时偏移): {self.web_vitals['cls_with_input']}")
        print(f"├─ INP (交互到下次绘制): {self.web_vitals['inp']} ms")
        print(f"└─ TTFB (首字节时间): {self.web_vitals['ttfb']} ms")
        print("\n[页面加载性能指标]")
        print(f"├─ 导航时间: {self.performance_metrics['navigation_time']} ms")
        print(f"├─ DNS 解析时间: {self.performance_metrics['dns_time']} ms")
        print(f"├─ TCP 连接时间: {self.performance_metrics['tcp_time']} ms")
        print(f"├─ SSL 握手时间: {self.performance_metrics['ssl_time']} ms")
        print(f"├─ 首字节时间 (TTFB): {self.performance_metrics['ttfb']} ms")
        print(f"├─ 页面完全加载时间: {self.performance_metrics['load_time']} ms")
        print(
            f"└─ DOM 内容加载完成时间: {self.performance_metrics['dom_content_loaded']} ms"
        )

        print("\n[资源加载统计]")

        resource_stats = self.performance_metrics["resource_stats"]

        print(f"├─ 总资源数: {resource_stats['total_resources']}")

        print(f"├─ 总资源大小: {resource_stats['total_size_kb']} KB")

        print(f"└─ 平均资源加载时间: {resource_stats['avg_resource_duration']} ms")

        print("\n[资源类型分布]")

        for resource_type, stats in resource_stats["by_type"].items():
            print(
                f"├─ {resource_type}: {stats['count']} 个, 总大小: {stats['total_size_kb']} KB, 平均加载时间: {stats['avg_duration']} ms"
            )

        print("\n" + "=" * 60)

        print("测试完成！")

        print("=" * 60)

    def _save_results(self):
        """保存测试结果到文件"""

        import os

        # 创建结果目录

        if not os.path.exists("./results"):
            os.makedirs("./results")

        # 指标含义解释

        metrics_explanations = {
            "web_vitals": {
                "fcp": "首次内容绘制(First Contentful Paint)：浏览器首次绘制任何文本、图像、非白色画布或SVG的时间点",
                "lcp": "最大内容绘制(Largest Contentful Paint)：视口中最大内容元素绘制完成的时间点，衡量页面主要内容加载速度",
                "cls": "累积布局偏移(Cumulative Layout Shift)：页面生命周期内所有没有最近用户输入的意外布局偏移的总和，衡量视觉稳定性",
                "cls_with_input": "包含交互的累积布局偏移：页面生命周期内所有布局偏移的总和，包括有最近用户输入的偏移，用于更全面的分析",
                "inp": "交互到下次绘制(Interaction to Next Paint)：衡量页面响应交互的速度，取所有交互中最长的处理时间",
                "ttfb": "首字节时间(Time to First Byte)：浏览器从服务器接收第一个字节的时间，衡量服务器响应速度",
            },
            "performance_metrics": {
                "ttfb": "首字节时间(Time to First Byte)：同上",
                "dns_time": "DNS解析时间：域名解析所需的时间",
                "tcp_time": "TCP连接时间：建立TCP连接所需的时间",
                "ssl_time": "SSL握手时间：建立HTTPS连接所需的SSL握手时间",
                "ttfp": "首字节接收时间：浏览器接收完整个响应的时间",
                "dom_content_loaded": "DOM内容加载完成时间：DOM树构建完成，所有脚本执行完成的时间",
                "load_time": "页面完全加载时间：所有资源(包括图片、样式等)加载完成的时间",
                "navigation_time": "导航总时间：从发起请求到页面可用的总时间",
                "resource_stats": {
                    "total_resources": "总资源数量：页面加载的所有资源文件数量",
                    "total_size_kb": "总资源大小：所有资源文件的总大小，单位KB",
                    "avg_resource_duration": "平均资源加载时间：所有资源的平均加载时长",
                    "by_type": "按资源类型统计：不同类型资源的加载情况，包括数量、大小和平均加载时间",
                },
            },
        }

        # 构建结果数据，包含指标解释

        result_data = {
            "test_info": {
                "test_url": self.url,
                "test_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "description": "Web性能测试报告，包含核心Web Vitals和页面性能指标",
            },
            "metrics_explanations": metrics_explanations,
            "web_vitals": self.web_vitals,
            "performance_metrics": self.performance_metrics,
        }

        # 保存为JSON文件

        filename = f"./results/performance_test_{time.strftime('%Y%m%d_%H%M%S')}.json"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(result_data, f, indent=2, ensure_ascii=False)

        print(f"\n测试结果已保存到: {filename}")

if __name__ == "__main__":
    # 测试URL
    #test_url = "https://www.clevguard.com/app/home"
    test_url = "https://www.monimaster.com/app/home"
    # 创建并运行性能测试
    test = WebPerformanceTest(test_url)
    test.run_test()