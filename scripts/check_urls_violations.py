# Author: pangguohao

"""
LitMedia.ai URL违规内容检查脚本
使用Playwright自动化工具检查sitemap中的所有URL是否包含违规内容
一次性检查所有URL并生成完整报告
"""

import json
from datetime import datetime
import re
from playwright.sync_api import sync_playwright
import time
import pandas as pd
from openpyxl.styles import Alignment
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# --- 修正后的关键词列表 ---
VIOLATION_KEYWORDS = [
    # --- 英文 (English) ---
    'nsfw', 'porn', 'pornography', 'adult video', 'adult content', 
    'nude', 'naked', 'explicit', '18+', 'erotic',

    # --- 繁体中文 (Traditional Chinese) ---
    '成人內容', '成人影片', '色情', '裸體', '露骨', '限制級', '十八禁', 
    '情色', '走光', '偷拍', '私密視頻', '無碼', '有碼',

    # --- 日语 (Japanese) ---
    'ポルノ', '成人向け', '18禁', '裏ビデオ', '全裸', 
    '露出', '卑猥', 'エロ', 'AV', '無修正', '着エロ',

     # --- 韩语 (Korean) ---
    '야동', '성인물', '포르노', '나체', '누드', '음란', 
    '19금', '노출', '성행위', '섹스', '직캠',

    # --- 法语 (French) ---
    'porno', 'nu', 'nudité', 'sexe', 'adulte seulement', 'érotique', 'vidéo adulte',

    # --- 西班牙语 (Spanish) ---
    'porno', 'desnudo', 'desnuda', 'sexo', 'erótico', 'solo adultos',

    # --- 巴西葡萄牙语 (Portuguese BR) ---
    'porno', 'pelada', 'pelado', 'nudez', 'sexo', 'conteúdo adulto',

    # --- 德语 (German) ---
    'porno', 'nackt', 'sexuell', 'erotik', 'ab 18',

    # --- 俄语 (Russian) ---
    'порно', 'секс', 'голая', 'обнаженная', 'эротика', 'порнография',

    # --- 阿拉伯语 (Arabic) ---
    'إباحي', 'جنس', 'عاري', 'للكبار فقط', 'بورنو'
]

def is_cjk(text):
    """
    判断文本是否包含中日韩字符
    """
    for char in text:
        if '\u4e00' <= char <= '\u9fff' or \
           '\u3040' <= char <= '\u30ff' or \
           '\uac00' <= char <= '\ud7af':
            return True
    return False

def get_regex_pattern(keyword):
    """
    根据语言类型生成正则模式
    如果是英文，添加单词边界 \b 以避免误伤
    如果是CJK（中日韩），直接匹配，因为这些语言通常没有空格分词
    """
    escaped_keyword = re.escape(keyword)
    if is_cjk(keyword):
        return escaped_keyword  # CJK 不加边界
    else:
        return r'\b' + escaped_keyword + r'\b'  # 英文加边界

def extract_violation_context(text, keyword, context_length=100):
    """
    提取包含违规关键词的上下文
    """
    contexts = []
    # 使用优化后的正则逻辑
    pattern = get_regex_pattern(keyword)
    
    try:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - context_length)
            end = min(len(text), match.end() + context_length)
            context = text[start:end].strip()
            # 清理上下文，移除多余空白
            context = re.sub(r'\s+', ' ', context)
            contexts.append(context)
    except Exception as e:
        print(f"上下文提取出错: {e}")
    
    return contexts[:5]  # 最多返回5个上下文

def check_url_for_violations(url, page, timeout=30000):
    """
    检查单个URL是否包含违规内容
    """
    result = {
        'url': url,
        'status': 'unknown',
        'violations': [],
        'error': None,
        'page_title': '',
        'page_text': '',
        'meta_description': ''
    }
    
    try:
        # 访问URL
        print(f"  正在检查: {url}")
        page.goto(url, wait_until='domcontentloaded', timeout=timeout)
        
        # 等待页面加载
        page.wait_for_timeout(2000)
        
        # 获取页面标题
        try:
            result['page_title'] = page.title()
        except:
            result['page_title'] = ''
        
        # 获取页面文本内容
        try:
            result['page_text'] = page.locator('body').inner_text()
            # 注意：此处不强制转小写进行存储，以便提取上下文时保持原样
            # 匹配时再转小写或使用 re.IGNORECASE
        except:
            result['page_text'] = ''
        
        # 获取meta描述
        try:
            meta_desc = page.locator('meta[name="description"]').get_attribute('content') or ''
            result['meta_description'] = meta_desc
        except:
            result['meta_description'] = ''
        
        # 准备用于匹配的小写文本
        url_lower = url.lower()
        title_lower = result['page_title'].lower()
        meta_desc_lower = result['meta_description'].lower()
        page_text_lower = result['page_text'].lower()
        
        # --- 核心检查逻辑 ---
        
        for keyword in VIOLATION_KEYWORDS:
            # 1. 检查URL
            if keyword in url_lower:
                result['violations'].append({
                    'type': 'URL包含违规关键词',
                    'keyword': keyword,
                    'location': 'URL',
                    'violation_text': url,
                    'context': []
                })
                continue # 如果URL本身违规，通常无需再检查内容，或者可以继续检查

            # 2. 检查标题 (使用优化后的正则)
            pattern = get_regex_pattern(keyword)
            if re.search(pattern, title_lower, re.IGNORECASE):
                 result['violations'].append({
                    'type': '页面标题包含违规关键词',
                    'keyword': keyword,
                    'location': 'Title',
                    'violation_text': result['page_title'],
                    'context': []
                })

            # 3. 检查Meta描述
            if meta_desc_lower and re.search(pattern, meta_desc_lower, re.IGNORECASE):
                result['violations'].append({
                    'type': 'Meta描述包含违规关键词',
                    'keyword': keyword,
                    'location': 'Meta Description',
                    'violation_text': result['meta_description'],
                    'context': []
                })

            # 4. 检查正文内容
            if page_text_lower:
                # 使用优化后的正则，兼顾英文边界和CJK连续字符
                matches = list(re.finditer(pattern, page_text_lower, re.IGNORECASE))
                
                if matches:
                    # 提取包含关键词的上下文（使用原始文本）
                    contexts = extract_violation_context(result['page_text'], keyword, context_length=150)
                    
                    # 提取包含关键词的句子
                    sentences = []
                    for match in matches:
                        start = max(0, match.start() - 200)
                        end = min(len(result['page_text']), match.end() + 200)
                        snippet = result['page_text'][start:end]
                        
                        # 尝试提取完整句子
                        sentence_match = re.search(r'[.!?。！？]\s*[^.!?。！？]*' + re.escape(keyword) + r'[^.!?。！？]*[.!?。！？]', snippet, re.IGNORECASE)
                        if sentence_match:
                            sentences.append(sentence_match.group().strip())
                        else:
                            sentences.append(snippet.strip())
                    
                    result['violations'].append({
                        'type': '页面内容包含违规关键词',
                        'keyword': keyword,
                        'location': 'Body',
                        'matches_count': len(matches),
                        'violation_text': sentences[:3] if sentences else contexts[:3],
                        'context': contexts[:5]
                    })
        
        # 设置状态
        if result['violations']:
            result['status'] = 'violation_found'
        else:
            result['status'] = 'clean'
            
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
        print(f"    [错误] {str(e)}")
    
    return result

def generate_complete_report(all_results, website='https://www.monimaster.com/'):
    """
    生成完整的检查报告
    
    Args:
        all_results: 所有检查结果
        website: 检查的网站URL
    """
    report = {
        '检查时间': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        '检查网站': website,
        '统计信息': {
            '总URL数': len(all_results),
            '发现违规': len([r for r in all_results if r['status'] == 'violation_found']),
            '正常': len([r for r in all_results if r['status'] == 'clean']),
            '错误': len([r for r in all_results if r['status'] == 'error'])
        },
        '违规URL详情': [],
        '正常URL列表': [],
        '错误URL列表': []
    }
    
    # 分类结果
    for result in all_results:
        if result['status'] == 'violation_found':
            violation_details = []
            for violation in result['violations']:
                detail = {
                    '违规类型': violation['type'],
                    '违规关键词': violation['keyword'],
                    '违规位置': violation['location']
                }
                
                if 'violation_text' in violation:
                    if isinstance(violation['violation_text'], list):
                        detail['违规文案'] = violation['violation_text']
                    else:
                        detail['违规文案'] = [violation['violation_text']]
                else:
                    detail['违规文案'] = []
                
                if 'context' in violation and violation['context']:
                    detail['上下文'] = violation['context']
                
                if 'matches_count' in violation:
                    detail['匹配次数'] = violation['matches_count']
                
                violation_details.append(detail)
            
            report['违规URL详情'].append({
                '链接': result['url'],
                '页面标题': result['page_title'],
                '违规数量': len(result['violations']),
                '违规详情': violation_details
            })
        elif result['status'] == 'clean':
            report['正常URL列表'].append(result['url'])
        elif result['status'] == 'error':
            report['错误URL列表'].append({
                '链接': result['url'],
                '错误信息': result['error']
            })
    
    return report

def detect_language_from_filename(filename):
    """
    从文件名中检测语言标识
    
    Args:
        filename: 文件名
        
    Returns:
        str: 语言标识（'en', 'kr', 'fr'等），如果无法识别则返回空字符串
    """
    filename_lower = filename.lower()
    # 检测 monimaster 站点的语言
    if 'monimaster' in filename_lower:
        if '_en' in filename_lower:
            return 'en'
        elif '_kr' in filename_lower:
            return 'kr'
        elif '_fr' in filename_lower:
            return 'fr'
        elif '_br' in filename_lower:
            return 'br'
        elif '_es' in filename_lower:
            return 'es'
        elif '_ru' in filename_lower:
            return 'ru'
        elif '_de' in filename_lower:
            return 'de'
        elif '_tw' in filename_lower:
            return 'tw'
        elif '_ar' in filename_lower:
            return 'ar'
    # 检测 litmedia 站点的语言
    elif 'litmedia' in filename_lower:
        if '_en' in filename_lower:
            return 'en'
        elif '_kr' in filename_lower:
            return 'kr'
        elif '_tw' in filename_lower:
            return 'tw'
        elif '_jp' in filename_lower:
            return 'jp'
    return ''

def save_report(report, language='', json_file=''):
    """
    保存报告到Excel文件
    
    Args:
        report: 报告数据
        language: 语言标识（用于生成文件名，如 'en', 'kr', 'fr'）
        json_file: JSON文件名（用于判断网站类型）
    """
    # 根据网站类型和语言生成文件名
    lang_suffix = f'_{language}' if language else ''
    
    # 判断是 litmedia 还是 monimaster
    if json_file and 'litmedia' in json_file.lower():
        site_name = 'litmedia'
    else:
        site_name = 'monimaster'
    
    excel_filename = f'violation_report_{site_name}{lang_suffix}.xlsx'
    
    # 生成Excel文件
    try:
        # 准备Excel数据
        excel_data = []
        
        for url_info in report.get('违规URL详情', []):
            url = url_info.get('链接', '')
            page_title = url_info.get('页面标题', '')
            violation_count = url_info.get('违规数量', 0)
            violations = url_info.get('违规详情', [])
            
            # 为每个违规项创建一行
            for violation in violations:
                violation_type = violation.get('违规类型', '')
                keyword = violation.get('违规关键词', '')
                location = violation.get('违规位置', '')
                violation_texts = violation.get('违规文案', [])
                contexts = violation.get('上下文', [])
                matches_count = violation.get('匹配次数', '')
                
                # 将违规文案列表合并为字符串
                violation_text = '\n'.join(violation_texts) if violation_texts else ''
                # 限制长度，避免Excel单元格过长
                if len(violation_text) > 1000:
                    violation_text = violation_text[:1000] + '...'
                
                # 将上下文列表合并为字符串
                context_text = '\n'.join(contexts[:3]) if contexts else ''  # 只取前3个上下文
                if len(context_text) > 500:
                    context_text = context_text[:500] + '...'
                
                excel_data.append({
                    '链接': url,
                    '页面标题': page_title,
                    '违规数量': violation_count,
                    '违规类型': violation_type,
                    '违规关键词': keyword,
                    '违规位置': location,
                    '匹配次数': matches_count if matches_count else '',
                    '违规文案': violation_text,
                    '上下文': context_text
                })
        
        # 创建DataFrame
        df = pd.DataFrame(excel_data)
        
        # 如果没有数据，创建一个空DataFrame
        if df.empty:
            df = pd.DataFrame(columns=['链接', '页面标题', '违规数量', '违规类型', '违规关键词', 
                                       '违规位置', '匹配次数', '违规文案', '上下文'])
        
        # 创建Excel写入器
        with pd.ExcelWriter(excel_filename, engine='openpyxl') as writer:
            # 写入违规详情表
            df.to_excel(writer, sheet_name='违规详情', index=False)
            
            # 获取工作表对象以调整列宽
            worksheet = writer.sheets['违规详情']
            
            # 调整列宽
            worksheet.column_dimensions['A'].width = 60  # 链接
            worksheet.column_dimensions['B'].width = 40  # 页面标题
            worksheet.column_dimensions['C'].width = 12  # 违规数量
            worksheet.column_dimensions['D'].width = 30  # 违规类型
            worksheet.column_dimensions['E'].width = 20  # 违规关键词
            worksheet.column_dimensions['F'].width = 20  # 违规位置
            worksheet.column_dimensions['G'].width = 12  # 匹配次数
            worksheet.column_dimensions['H'].width = 80  # 违规文案
            worksheet.column_dimensions['I'].width = 80  # 上下文
            
            # 设置文本换行
            for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row):
                for cell in row:
                    cell.alignment = Alignment(wrap_text=True, vertical='top')
            
            # 创建统计信息表
            stats_data = {
                '项目': ['检查时间', '检查网站', '总URL数', '发现违规', '正常', '错误'],
                '数值': [
                    report.get('检查时间', ''),
                    report.get('检查网站', ''),
                    report.get('统计信息', {}).get('总URL数', 0),
                    report.get('统计信息', {}).get('发现违规', 0),
                    report.get('统计信息', {}).get('正常', 0),
                    report.get('统计信息', {}).get('错误', 0)
                ]
            }
            stats_df = pd.DataFrame(stats_data)
            stats_df.to_excel(writer, sheet_name='统计信息', index=False)
            
            # 调整统计信息表列宽
            stats_worksheet = writer.sheets['统计信息']
            stats_worksheet.column_dimensions['A'].width = 20
            stats_worksheet.column_dimensions['B'].width = 50
            
            # 创建违规URL汇总表（每个URL一行）
            summary_data = []
            for url_info in report.get('违规URL详情', []):
                summary_data.append({
                    '链接': url_info.get('链接', ''),
                    '页面标题': url_info.get('页面标题', ''),
                    '违规数量': url_info.get('违规数量', 0)
                })
            
            if summary_data:
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='违规URL汇总', index=False)
                
                # 调整汇总表列宽
                summary_worksheet = writer.sheets['违规URL汇总']
                summary_worksheet.column_dimensions['A'].width = 60
                summary_worksheet.column_dimensions['B'].width = 40
                summary_worksheet.column_dimensions['C'].width = 12
        
        print(f"\n[OK] Excel报告已保存: {excel_filename}")
        print(f"  - 共 {len(excel_data)} 条违规记录")
    except Exception as e:
        print(f"\n[警告] Excel文件生成失败: {str(e)}")
        import traceback
        traceback.print_exc()

def check_url_worker(url, worker_id, total_urls, progress_lock, progress_counter):
    """
    工作线程函数：使用独立的浏览器实例检查单个URL
    
    Args:
        url: 要检查的URL
        worker_id: 工作线程ID
        total_urls: 总URL数
        progress_lock: 进度锁
        progress_counter: 进度计数器 [已完成数量]
        
    Returns:
        dict: 检查结果
    """
    result = {
        'url': url,
        'status': 'unknown',
        'violations': [],
        'error': None,
        'page_title': '',
        'page_text': '',
        'meta_description': ''
    }
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            context.route("**/*.{png,jpg,jpeg,svg,gif,woff,woff2}", lambda route: route.abort())
            page = context.new_page()
            
            try:
                result = check_url_for_violations(url, page)
                
                # 线程安全地更新进度
                with progress_lock:
                    progress_counter[0] += 1
                    current = progress_counter[0]
                    status_msg = ""
                    if result['status'] == 'violation_found':
                        status_msg = f"  [警告 违规] 发现 {len(result['violations'])} 处违规内容"
                    elif result['status'] == 'clean':
                        status_msg = "  [正常] 未发现违规内容"
                    elif result['status'] == 'error':
                        status_msg = f"  [错误] {result['error']}"
                    
                    print(f"[{current}/{total_urls}] [Worker-{worker_id}] {url}{status_msg}")
            finally:
                browser.close()
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
        with progress_lock:
            progress_counter[0] += 1
            current = progress_counter[0]
            print(f"[{current}/{total_urls}] [Worker-{worker_id}] {url}  [错误] {str(e)}")
    
    return result

def process_single_language(json_file):
    """
    处理单个语言的JSON文件（使用10个浏览器并行处理）
    
    Args:
        json_file: JSON文件路径
        
    Returns:
        bool: 是否成功处理
    """
    print(f"\n{'=' * 100}")
    print(f"正在处理: {json_file}")
    print('=' * 100)
    
    # 从文件名检测语言
    language = detect_language_from_filename(json_file)
    lang_names = {
        'en': '英文', 'kr': '韩语', 'fr': '法语', 'br': '巴西葡萄牙语',
        'es': '西班牙语', 'ru': '俄语', 'de': '德语', 'tw': '繁体中文', 
        'ar': '阿拉伯语', 'jp': '日语'
    }
    lang_display = lang_names.get(language, language) if language else '未知'
    
    if language:
        print(f"检测到语言: {lang_display}\n")
    
    # 读取JSON文件
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"[错误] 找不到文件 '{json_file}'")
        return False
    except json.JSONDecodeError as e:
        print(f"[错误] JSON文件解析失败: {e}")
        return False
    
    # 从JSON中获取网站信息
    website = data.get('sitemap来源', 'https://www.monimaster.com/')
    if 'sitemap来源' in data:
        # 从sitemap来源提取网站URL
        sitemap_url = data['sitemap来源']
        if 'monimaster.com' in sitemap_url:
            website = 'https://www.monimaster.com/'
    
    # 兼容不同的JSON结构
    if isinstance(data, list):
        urls = [item.get('url') if isinstance(item, dict) else item for item in data]
    elif 'URL列表' in data:
        urls = [item['url'] for item in data['URL列表']]
    else:
        urls = []
        possible_keys = ['urls', 'links', 'sitemap']
        for k in possible_keys:
            if k in data:
                urls = [item['url'] if isinstance(item, dict) else item for item in data[k]]
                break
    
    # 过滤空URL
    urls = [u for u in urls if u]
    
    total_urls = len(urls)
    if total_urls == 0:
        print(f"[警告] 未找到任何URL，跳过此文件")
        return False
    
    print(f"共找到 {total_urls} 个URL")
    print(f"使用10个浏览器并行处理...\n")
    
    # 线程安全的进度计数器
    progress_lock = threading.Lock()
    progress_counter = [0]  # 使用列表以便在函数间共享
    
    all_results = []
    
    # 使用线程池并行处理，最多10个浏览器
    with ThreadPoolExecutor(max_workers=10) as executor:
        # 提交所有任务
        future_to_url = {
            executor.submit(check_url_worker, url, (i % 10) + 1, total_urls, progress_lock, progress_counter): url
            for i, url in enumerate(urls)
        }
        
        # 收集结果
        for future in as_completed(future_to_url):
            try:
                result = future.result()
                all_results.append(result)
            except Exception as e:
                url = future_to_url[future]
                print(f"[错误] 处理 {url} 时发生异常: {e}")
                all_results.append({
                    'url': url,
                    'status': 'error',
                    'error': str(e),
                    'violations': [],
                    'page_title': '',
                    'page_text': '',
                    'meta_description': ''
                })
    
    # 按原始URL顺序排序结果
    url_to_result = {r['url']: r for r in all_results}
    all_results = [url_to_result.get(url, {
        'url': url,
        'status': 'error',
        'error': '未处理',
        'violations': [],
        'page_title': '',
        'page_text': '',
        'meta_description': ''
    }) for url in urls]
    
    print(f"\n{'=' * 100}")
    print("正在生成报告...")
    print('=' * 100)
    report = generate_complete_report(all_results, website)
    save_report(report, language, json_file)
    
    # 显示摘要
    print(f"\n{'=' * 100}")
    print(f"{lang_display}站点检查完成！摘要:")
    print('=' * 100)
    print(f"总URL数: {report['统计信息']['总URL数']}")
    print(f"发现违规: {report['统计信息']['发现违规']}")
    print(f"正常: {report['统计信息']['正常']}")
    print(f"错误: {report['统计信息']['错误']}")
    
    if report['违规URL详情']:
        print(f"\n发现违规的链接 (前5个示例):")
        for item in report['违规URL详情'][:5]:
            print(f"  - {item['链接']} (违规数量: {item['违规数量']})")
        if len(report['违规URL详情']) > 5:
            print(f"  ... 更多详情请查看生成的Excel文件")
    
    return True

def main():
    """
    主函数：依次处理所有monimaster站点的JSON文件
    """
    print('=' * 100)
    print('URL违规内容检查工具')
    print('=' * 100)
    print('将依次处理所有站点的JSON文件（Monimaster 和 LitMedia），每个语言生成独立的Excel报告\n')
    
    # 定义要处理的JSON文件列表（包括 monimaster 和 litmedia）
    monimaster_files = [
        # Monimaster 站点
        # 'monimaster_sitemap_urls_en.json',
        # 'monimaster_sitemap_urls_kr.json',
        # 'monimaster_sitemap_urls_fr.json',
        # 'monimaster_sitemap_urls_br.json',
        # 'monimaster_sitemap_urls_es.json',
        # 'monimaster_sitemap_urls_ru.json',
        # 'monimaster_sitemap_urls_de.json',
        # 'monimaster_sitemap_urls_tw.json',
        # 'monimaster_sitemap_urls_ar.json',
        # LitMedia 站点
        # 'litmedia_sitemap_urls_en.json',
        # 'litmedia_sitemap_urls_tw.json',
        # 'litmedia_sitemap_urls_kr.json',
        # 'litmedia_sitemap_urls_jp.json'
    ]
    
    # 检查哪些文件存在
    existing_files = []
    for json_file in monimaster_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                json.load(f)  # 测试是否能读取
            existing_files.append(json_file)
        except FileNotFoundError:
            print(f"[跳过] 文件不存在: {json_file}")
        except json.JSONDecodeError:
            print(f"[跳过] JSON格式错误: {json_file}")
    
    if not existing_files:
        print("\n[错误] 未找到任何JSON文件！")
        print("请确保以下文件之一存在：")
        for json_file in monimaster_files:
            print(f"  - {json_file}")
        return
    
    print(f"\n找到 {len(existing_files)} 个文件，将依次处理：")
    for json_file in existing_files:
        print(f"  - {json_file}")
    
    print(f"\n{'=' * 100}")
    print("开始处理...")
    print('=' * 100)
    
    # 依次处理每个文件
    successful_count = 0
    failed_count = 0
    
    for idx, json_file in enumerate(existing_files, 1):
        print(f"\n\n{'#' * 100}")
        print(f"处理进度: [{idx}/{len(existing_files)}]")
        print(f"{'#' * 100}")
        
        if process_single_language(json_file):
            successful_count += 1
        else:
            failed_count += 1
    
    # 最终总结
    print(f"\n\n{'=' * 100}")
    print("所有处理完成！")
    print('=' * 100)
    print(f"成功处理: {successful_count} 个文件")
    print(f"处理失败: {failed_count} 个文件")
    print(f"总计: {len(existing_files)} 个文件")
    print(f"\n每个语言的Excel报告已生成，文件名格式:")
    print(f"  - LitMedia: violation_report_litmedia_<语言>.xlsx")
    print(f"  - Monimaster: violation_report_monimaster_<语言>.xlsx")
    print('=' * 100)

if __name__ == "__main__":
    main()