import requests
from datetime import datetime, timezone
import pytz
import os
import time
import hmac
import hashlib
import base64
import urllib.parse

# 修改配置信息部分
NOTION_TOKEN = os.environ.get('NOTION_TOKEN', "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")
DATABASE_ID = os.environ.get('DATABASE_ID', "192ed4b7aaea81859bbbf3ad4ea54b56")
PUSHPLUS_TOKEN = os.environ.get('PUSHPLUS_TOKEN', "3cfcadc8fcf744769292f0170e724ddb")

# 在配置部分添加 WxPusher 配置
WXPUSHER_TOKEN = "AT_wO2h16sJxNbV0pR3wOvssCi5eGKomrhH"
WXPUSHER_UID = "UID_Kp0Ftm3F0GmnGmdYnmKY3yBet7u4"

# 四象限优先级
PRIORITY_ORDER = {
    "P0 重要紧急": 0,
    "P1 重要不紧急": 1,
    "P2 紧急不重要": 2,
    "P3 不重要不紧急": 3
}

# 添加钉钉配置
DINGTALK_TOKEN = "812a9229191e0073b8e8f7b8634566be7ad6c76250e62ed98335d29d342c1336"
DINGTALK_SECRET = "SEC49c94c1d04babd709d033051569ed245d99857f5c744f77656abd15bd30abf90"
DINGTALK_WEBHOOK = f"https://oapi.dingtalk.com/robot/send?access_token={DINGTALK_TOKEN}"

def get_notion_tasks(is_evening=False):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    if is_evening:
        # 晚上查询当天已完成的任务
        body = {
            "filter": {
                "and": [
                    {
                        "property": "状态",
                        "status": {
                            "equals": "已完成"
                        }
                    }
                ]
            },
            "sorts": [
                {
                    "timestamp": "last_edited_time",
                    "direction": "descending"
                }
            ]
        }
    else:
        # 早上的待办任务查询保持不变
        body = {
            "filter": {  # 添加 filter 包装
                "and": [
                    {
                        "or": [
                            {
                                "property": "状态",
                                "status": {
                                    "equals": "还未开始"
                                }
                            },
                            {
                                "property": "状态",
                                "status": {
                                    "equals": "进行中"
                                }
                            }
                        ]
                    },
                    {
                        "property": "开始日期",
                        "date": {
                            "on_or_before": today
                        }
                    }
                ]
            },
            "sorts": [
                {
                    "property": "四象限",
                    "direction": "ascending"
                }
            ]
        }
    
    try:
        print("正在发送请求到Notion API...")
        print(f"查询条件: {body}")  # 添加这行来打印查询条件
        response = requests.post(
            f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
            headers=headers,
            json=body
        )
        print(f"Notion API响应状态码: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Notion API错误: {response.text}")
            return {"results": []}
            
        return response.json()
    except Exception as e:
        print(f"获取Notion任务时出错: {str(e)}")
        return {"results": []}

def format_message(tasks_data):
    """格式化早上的待办任务消息"""
    messages = []
    tasks_by_assignee = {}
    
    # 初始化数据结构
    for result in tasks_data.get('results', []):
        properties = result.get('properties', {})
        
        # 获取任务信息
        name = properties.get('任务名称', {}).get('title', [{}])[0].get('plain_text', '未命名任务')
        assignee = properties.get('负责人', {}).get('select', {}).get('name', '未分配')
        priority = properties.get('四象限', {}).get('select', {}).get('name', 'P3 不重要不紧急')
        task_type = properties.get('任务类型', {}).get('select', {}).get('name', '未分类')
        due_date = properties.get('截止日期', {}).get('date', {}).get('start', '未设置')
        
        # 初始化该负责人的任务列表
        if assignee not in tasks_by_assignee:
            tasks_by_assignee[assignee] = []
        
        # 添加任务，包含优先级信息
        priority_short = 'P' + str(PRIORITY_ORDER.get(priority, 3))
        tasks_by_assignee[assignee].append({
            'name': name,
            'type': task_type,
            'due_date': due_date,
            'priority': priority,
            'priority_short': priority_short,
            'days_diff': (datetime.strptime(due_date, '%Y-%m-%d').date() - datetime.now().date()).days if due_date != '未设置' else None
        })
    
    for assignee, tasks in tasks_by_assignee.items():
        # 统计信息
        p0_count = sum(1 for t in tasks if 'P0' in t['priority'])
        p1_count = sum(1 for t in tasks if 'P1' in t['priority'])
        overdue_count = sum(1 for t in tasks if t['days_diff'] is not None and t['days_diff'] < 0)
        
        message = [
            f"📋 待办任务 | {assignee} (共{len(tasks)}条)\n"
        ]
        
        # 按优先级排序任务
        tasks.sort(key=lambda x: PRIORITY_ORDER.get(x['priority'], 3))
        
        # 添加任务列表
        for i, task in enumerate(tasks, 1):
            message.append(
                f"{i}. {task['name']} | {task['type']} | {task['priority_short']} | {task['due_date']}"
            )
        
        # 添加统计信息
        message.append(f"\n📊 统计: P0 {p0_count} | P1 {p1_count} | 逾期{overdue_count}")
        
        messages.append("\n".join(message))
    
    # 为钉钉消息添加分隔线
    return "\n\n---\n\n".join(messages) if len(messages) > 1 else messages[0]

def format_evening_message(tasks_data):
    """格式化晚上的完成任务消息"""
    # 过滤今天完成的任务
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_tasks = [
        result for result in tasks_data.get('results', [])
        if result.get('last_edited_time', '').startswith(today)
    ]
    
    total_tasks = len(today_tasks)
    if total_tasks == 0:
        return "✅ 今日完成 (0/0)\n\n还没有完成任何任务哦！加油！"
    
    # 假设总任务数是完成任务的1.5倍（你可以根据实际情况调整）
    estimated_total = max(total_tasks, round(total_tasks * 1.5))
    completion_rate = round((total_tasks / estimated_total) * 100)
    
    message = [f"✅ 今日完成 ({total_tasks}/{estimated_total})"]
    
    # 统计信息初始化
    important_count = 0
    urgent_count = 0
    
    # 添加任务列表
    for idx, result in enumerate(today_tasks, 1):
        properties = result.get('properties', {})
        name = properties.get('任务名称', {}).get('title', [{}])[0].get('plain_text', '未命名任务')
        task_type = properties.get('任务类型', {}).get('select', {}).get('name', '未分类')
        priority = properties.get('四象限', {}).get('select', {}).get('name', 'P3')
        
        # 统计重要和紧急任务
        if 'P0' in priority or 'P1' in priority:
            important_count += 1
        if 'P0' in priority or 'P2' in priority:
            urgent_count += 1
        
        message.append(f"{idx}. {name} | {task_type} | {priority[:2]}")
    
    # 添加统计信息
    message.append(f"\n📊 完成率: {completion_rate}% | 重要{important_count} | 紧急{urgent_count}")
    
    return "\n\n".join(message)

def send_to_wechat(message):
    url = "http://www.pushplus.plus/send"
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": "任务提醒",  # 简化标题
        "content": message,
        "template": "txt",
        "channel": "wechat"  # 明确指定渠道
    }
    
    try:
        print(f"正在发送消息到PushPlus...")
        print(f"请求URL: {url}")
        print(f"请求数据: {data}")
        
        response = requests.post(url, json=data, timeout=10)
        print(f"响应状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")
        print(f"响应内容: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 200:
                print("消息发送成功")
                return True
            else:
                print(f"PushPlus返回错误: {result}")
                return False
        else:
            print(f"HTTP请求失败: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"发送消息时出错: {str(e)}")
        return False

def send_to_dingtalk(message):
    """发送消息到钉钉群"""
    try:
        # 生成时间戳和签名
        timestamp = str(round(time.time() * 1000))
        secret = DINGTALK_SECRET
        secret_enc = secret.encode('utf-8')
        string_to_sign = '{}\n{}'.format(timestamp, secret)
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        
        # 构建完整的URL
        url = f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"
        
        print(f"\n=== 钉钉发送信息 ===")
        print(f"时间戳: {timestamp}")
        print(f"目标URL: {url}")
        
        # 构建消息内容，确保分隔线正确显示
        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": "任务提醒",
                "text": message.replace("---", "---\n")  # 确保分隔线正确显示
            }
        }
        
        print(f"发送数据: {data}")
        
        # 发送请求
        response = requests.post(url, json=data, timeout=10)
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('errcode') == 0:
                print("钉钉消息发送成功")
                return True
            else:
                print(f"钉钉返回错误: {result}")
                return False
        else:
            print(f"HTTP请求失败: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"钉钉发送失败: {str(e)}")
        return False

def send_to_wxpusher(message):
    """发送消息到 WxPusher"""
    url = "http://wxpusher.zjiecode.com/api/send/message"
    data = {
        "appToken": WXPUSHER_TOKEN,
        "content": message,
        "contentType": 1,  # 1表示文本
        "uids": [WXPUSHER_UID],
        "summary": "任务提醒"  # 消息摘要
    }
    
    try:
        print(f"\n=== WxPusher 发送信息 ===")
        print(f"请求URL: {url}")
        print(f"发送数据: {data}")
        
        response = requests.post(url, json=data, timeout=10)
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print("WxPusher消息发送成功")
                return True
            else:
                print(f"WxPusher返回错误: {result}")
                return False
        else:
            print(f"HTTP请求失败: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"WxPusher发送失败: {str(e)}")
        return False

def send_message(message):
    """统一的消息发送函数"""
    results = []
    
    # PushPlus 推送
    print("\n=== 开始 PushPlus 推送 ===")
    pushplus_result = send_to_wechat(message)
    results.append(pushplus_result)
    print(f"PushPlus发送{'成功' if pushplus_result else '失败'}")
    
    # 钉钉推送
    print("\n=== 开始钉钉推送 ===")
    dingtalk_result = send_to_dingtalk(message)
    results.append(dingtalk_result)
    print(f"钉钉发送{'成功' if dingtalk_result else '失败'}")
    
    # WxPusher 推送
    print("\n=== 开始 WxPusher 推送 ===")
    wxpusher_result = send_to_wxpusher(message)
    results.append(wxpusher_result)
    print(f"WxPusher发送{'成功' if wxpusher_result else '失败'}")
    
    return any(results)

def wait_until_send_time():
    beijing_tz = pytz.timezone('Asia/Shanghai')
    target_time_str = os.environ.get('SEND_TIME', '08:00')  # 默认早上8点
    
    now = datetime.now(beijing_tz)
    target_time = datetime.strptime(target_time_str, '%H:%M').time()
    target_datetime = datetime.combine(now.date(), target_time)
    target_datetime = beijing_tz.localize(target_datetime)
    
    if now.time() > target_time:
        # 如果当前时间已经过了目标时间，说明是测试运行，立即发送
        return
    
    wait_seconds = (target_datetime - now).total_seconds()
    if wait_seconds > 0:
        print(f"等待发送时间，将在 {target_time_str} 发送...")
        time.sleep(wait_seconds)

def main():
    try:
        # 添加时间调试信息
        beijing_tz = pytz.timezone('Asia/Shanghai')
        utc_now = datetime.now(timezone.utc)
        beijing_now = utc_now.astimezone(beijing_tz)
        
        print(f"\n=== 时间信息 ===")
        print(f"UTC 时间: {utc_now}")
        print(f"北京时间: {beijing_now}")
        print(f"目标发送时间: {os.environ.get('SEND_TIME', '08:00')}")
        print(f"执行类型: {os.environ.get('REMINDER_TYPE', '未设置')}")
        print("=== 时间信息结束 ===\n")
        
        # 检查环境变量
        print("检查环境变量...")
        print(f"PUSHPLUS_TOKEN: {PUSHPLUS_TOKEN[:8]}*** (长度: {len(PUSHPLUS_TOKEN)})")
        print(f"REMINDER_TYPE: {os.environ.get('REMINDER_TYPE', '未设置')}")
        print(f"NOTION_TOKEN: {'已设置' if NOTION_TOKEN else '未设置'}")
        print(f"DATABASE_ID: {'已设置' if DATABASE_ID else '未设置'}")
        
        # 提前获取和处理数据
        is_evening = os.environ.get('REMINDER_TYPE') == 'evening'
        print(f"开始获取{'已完成' if is_evening else '待处理'}任务...")
        tasks = get_notion_tasks(is_evening)
        
        if not tasks.get('results'):
            print("没有获取到任何任务")
            return
            
        print(f"获取到 {len(tasks.get('results', []))} 个任务")
        
        print("格式化消息...")
        message = format_evening_message(tasks) if is_evening else format_message(tasks)
        
        if not message.strip():
            print("没有需要提醒的任务")
            return
        
        # 等待到指定时间
        wait_until_send_time()
        
        print("发送消息...")
        if send_message(message):  # 使用新的 send_message 函数
            print("至少一个渠道发送成功!")
        else:
            print("所有渠道发送失败!")
    except Exception as e:
        print(f"运行出错: {str(e)}")
        raise

if __name__ == "__main__":
    main()
