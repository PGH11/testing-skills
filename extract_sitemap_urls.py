"""
从LitMedia.ai的sitemap XML文件中提取所有URL并保存为JSON
支持提取英文和日语站点的URL
"""

import json
import xml.etree.ElementTree as ET
import requests
from datetime import datetime

def extract_urls_from_sitemap(sitemap_url, language='en'):
    """
    从sitemap XML中提取所有URL
    
    Args:
        sitemap_url: sitemap的URL地址
        language: 语言标识（'en' 或 'jp'）
    
    Returns:
        list: URL数据列表，每个URL包含url、lastmod、changefreq、priority和language字段
    """
    
    print(f"正在获取sitemap: {sitemap_url}")
    
    try:
        # 获取sitemap内容
        response = requests.get(sitemap_url, timeout=30)
        response.raise_for_status()
        
        # 解析XML
        root = ET.fromstring(response.content)
        
        # 定义命名空间
        namespaces = {
            'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'
        }
        
        urls = []
        
        # 提取所有URL
        for url_elem in root.findall('ns:url', namespaces):
            url_data = {}
            
            # 获取loc（URL地址）
            loc = url_elem.find('ns:loc', namespaces)
            if loc is not None:
                url_data['url'] = loc.text
            
            # 获取lastmod（最后修改时间）
            lastmod = url_elem.find('ns:lastmod', namespaces)
            if lastmod is not None:
                url_data['lastmod'] = lastmod.text
            
            # 获取changefreq（更新频率）
            changefreq = url_elem.find('ns:changefreq', namespaces)
            if changefreq is not None:
                url_data['changefreq'] = changefreq.text
            
            # 获取priority（优先级）
            priority = url_elem.find('ns:priority', namespaces)
            if priority is not None:
                url_data['priority'] = priority.text
            
            # 添加语言标识
            url_data['language'] = language
            
            if url_data.get('url'):
                urls.append(url_data)
        
        print(f"  成功提取 {len(urls)} 个URL")
        return urls
    
    except requests.RequestException as e:
        print(f"  获取sitemap失败: {e}")
        return None
    except ET.ParseError as e:
        print(f"  解析XML失败: {e}")
        return None

def save_to_json(urls, output_file, sitemap_url, language_name):
    """
    保存URL列表到JSON文件（单个语言）
    
    Args:
        urls: URL列表
        output_file: 输出文件名
        sitemap_url: sitemap来源URL
        language_name: 语言名称（用于显示）
    """
    
    # 移除language字段，因为每个文件只包含一种语言
    cleaned_urls = []
    for url_data in urls:
        cleaned_data = {k: v for k, v in url_data.items() if k != 'language'}
        cleaned_urls.append(cleaned_data)
    
    result = {
        "提取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sitemap来源": sitemap_url,
        "语言": language_name,
        "URL总数": len(cleaned_urls),
        "URL列表": cleaned_urls
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"  成功保存 {len(cleaned_urls)} 个URL到 {output_file}")

if __name__ == "__main__":
    # 定义要提取的sitemap列表
    sitemaps = [
        {
            'url': 'https://www.litmedia.ai/sitemap_en.xml',
            'language': 'en',
            'name': '英文站点',
            'output_file': 'litmedia_sitemap_urls_en.json'
        },
        {
            'url': 'https://www.litmedia.ai/sitemap_jp.xml',
            'language': 'jp',
            'name': '日语站点',
            'output_file': 'litmedia_sitemap_urls_jp.json'
        },
        {
            'url': 'https://www.litmedia.ai/sitemap_tw.xml',
            'language': 'tw',
            'name': '繁体中文站点',
            'output_file': 'litmedia_sitemap_urls_tw.json'
        },
        {
            'url': 'https://www.litmedia.ai/sitemap_kr.xml',
            'language': 'kr',
            'name': '韩语站点',
            'output_file': 'litmedia_sitemap_urls_kr.json'
        },
        {
            'url': 'https://www.monimaster.com/sitemap_en.xml',
            'language': 'en',
            'name': 'Monimaster英文站点',
            'output_file': 'monimaster_sitemap_urls_en.json'
        },
        {
            'url': 'https://www.monimaster.com/sitemap_kr.xml',
            'language': 'kr',
            'name': 'Monimaster韩语站点',
            'output_file': 'monimaster_sitemap_urls_kr.json'
        },
        {
            'url': 'https://www.monimaster.com/sitemap_fr.xml',
            'language': 'fr',
            'name': 'Monimaster法语站点',
            'output_file': 'monimaster_sitemap_urls_fr.json'
        },
        {
            'url': 'https://www.monimaster.com/sitemap_br.xml',
            'language': 'br',
            'name': 'Monimaster巴西葡萄牙语站点',
            'output_file': 'monimaster_sitemap_urls_br.json'
        },
        {
            'url': 'https://www.monimaster.com/sitemap_es.xml',
            'language': 'es',
            'name': 'Monimaster西班牙语站点',
            'output_file': 'monimaster_sitemap_urls_es.json'
        },
        {
            'url': 'https://www.monimaster.com/sitemap_ru.xml',
            'language': 'ru',
            'name': 'Monimaster俄语站点',
            'output_file': 'monimaster_sitemap_urls_ru.json'
        },
        {
            'url': 'https://www.monimaster.com/sitemap_de.xml',
            'language': 'de',
            'name': 'Monimaster德语站点',
            'output_file': 'monimaster_sitemap_urls_de.json'
        },
        {
            'url': 'https://www.monimaster.com/sitemap_tw.xml',
            'language': 'tw',
            'name': 'Monimaster繁体中文站点',
            'output_file': 'monimaster_sitemap_urls_tw.json'
        },
        {
            'url': 'https://www.monimaster.com/sitemap_ar.xml',
            'language': 'ar',
            'name': 'Monimaster阿拉伯语站点',
            'output_file': 'monimaster_sitemap_urls_ar.json'
        }
    ]
    
    print("=" * 60)
    print("Sitemap URL提取工具")
    print("=" * 60)
    print("支持提取LitMedia.ai和Monimaster.com的多语言站点URL，每个语言单独保存\n")
    
    successful_extractions = []
    total_urls = 0
    
    # 提取并保存每个语言的sitemap
    for sitemap_info in sitemaps:
        print(f"\n处理 {sitemap_info['name']} ({sitemap_info['url']})...")
        urls = extract_urls_from_sitemap(sitemap_info['url'], sitemap_info['language'])
        
        if urls:
            # 保存到单独的JSON文件
            save_to_json(urls, sitemap_info['output_file'], sitemap_info['url'], sitemap_info['name'])
            successful_extractions.append({
                'name': sitemap_info['name'],
                'file': sitemap_info['output_file'],
                'count': len(urls)
            })
            total_urls += len(urls)
        else:
            print(f"  [警告] {sitemap_info['name']} 提取失败，跳过")
    
    if successful_extractions:
        # 显示统计信息
        print("\n" + "=" * 60)
        print("统计信息")
        print("=" * 60)
        print(f"总URL数量: {total_urls}")
        
        print(f"\n各语言URL统计:")
        for extraction in successful_extractions:
            print(f"  {extraction['name']}: {extraction['count']} 个URL")
        
        # 显示各语言的前5个URL作为示例
        print(f"\nURL示例:")
        for extraction in successful_extractions:
            # 读取已保存的文件来显示示例
            try:
                with open(extraction['file'], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    urls_list = data.get('URL列表', [])
                    if urls_list:
                        print(f"\n  {extraction['name']}前5个URL:")
                        for i, url_data in enumerate(urls_list[:5], 1):
                            print(f"    {i}. {url_data.get('url', 'N/A')}")
            except:
                pass
        
        print("\n" + "=" * 60)
        print("文件保存位置:")
        for extraction in successful_extractions:
            print(f"  {extraction['name']}: {extraction['file']}")
        print("=" * 60)
    else:
        print("\n提取URL失败，请检查网络连接或sitemap URL是否正确")

