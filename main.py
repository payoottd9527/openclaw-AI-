#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🥔 小土豆NVIDIA NIM全自动密钥轮换系统
支持188个模型的API密钥自动生成和轮换
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path

from core.key_manager import KeyManager
from core.pool_manager import pool_manager
from providers.nvidia.key_rotator import NVIDIAKeyRotator
from providers.nvidia.model_selector import ModelSelector
import config

# 配置日志
logging.basicConfig(
    level=getattr(logging, config.LOG_CONFIG['level']),
    format=config.LOG_CONFIG['format'],
    handlers=[
        logging.FileHandler(config.LOG_CONFIG['file']),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('🥔NIMRotator')

class NIMKeyRotationSystem:
    """NVIDIA NIM密钥轮换系统"""
    
    def __init__(self):
        logger.info("🥔 初始化NIM密钥轮换系统...")
        
        # 初始化数据库
        self.key_manager = KeyManager(config.DATABASE_CONFIG['keys_db'])
        
        # 初始化池管理器
        pool_manager.init(config.POOL_CONFIG)
        
        # 初始化密钥轮换器
        self.key_rotator = NVIDIAKeyRotator(config.NVIDIA_CONFIG, self.key_manager)
        
        # 初始化模型选择器
        self.model_selector = ModelSelector(
            'models.json', 
            self.key_manager,
            config.NVIDIA_CONFIG
        )
        
        logger.info("✅ 系统初始化完成")
    
    def run(self, args):
        """运行系统"""
        if args.action == 'rotate':
            self._rotate_keys(args)
        elif args.action == 'create':
            self._create_keys(args)
        elif args.action == 'list':
            self._list_keys(args)
        elif args.action == 'monitor':
            self._monitor(args)
        elif args.action == 'test':
            self._test_model(args)
        else:
            self._auto_run(args)
    
    def _rotate_keys(self, args):
        """轮换密钥"""
        logger.info("🔄 开始轮换密钥...")
        
        if args.all:
            # 轮换所有即将过期的密钥
            self.key_rotator.rotate_all_keys(days_before_expiry=args.days)
        elif args.key_id:
            # 轮换指定密钥
            # TODO: 实现单个密钥轮换
            pass
    
    def _create_keys(self, args):
        """创建新密钥"""
        logger.info(f"🔑 开始创建 {args.count} 个新密钥...")
        
        model_types = args.types.split(',') if args.types else None
        self.key_rotator.create_new_keys(count=args.count, model_types=model_types)
    
    def _list_keys(self, args):
        """列出密钥"""
        logger.info("📋 列出所有密钥...")
        
        stats = self.key_manager.get_account_stats()
        print("\n" + "="*60)
        print(f"🥔 密钥统计")
        print("="*60)
        print(f"总账号数: {stats.get('total_accounts', 0)}")
        print(f"总密钥数: {stats.get('total_keys', 0)}")
        print(f"活跃密钥: {stats.get('active_keys', 0)}")
        print(f"过期密钥: {stats.get('expired_keys', 0)}")
        print(f"总使用次数: {stats.get('total_usage', 0)}")
        print("="*60 + "\n")
        
        if args.detail:
            with self.key_manager.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT a.email, a.status, a.total_keys,
                           k.key_name, k.key_value, k.expires_at, k.usage_count
                    FROM accounts a
                    LEFT JOIN api_keys k ON a.id = k.account_id
                    ORDER BY a.created_at DESC
                ''')
                
                for row in cursor.fetchall():
                    print(f"账号: {row['email']} | 状态: {row['status']} | 密钥数: {row['total_keys']}")
                    if row['key_name']:
                        print(f"  ├─ {row['key_name']}")
                        print(f"  │  ├─ 过期: {row['expires_at']}")
                        print(f"  │  └─ 使用: {row['usage_count']}次")
                    print()
    
    def _monitor(self, args):
        """监控密钥状态"""
        logger.info("👀 开始监控密钥状态...")
        
        while True:
            try:
                # 检查即将过期的密钥
                expiring = self.key_manager.get_expiring_keys(days=args.days or 3)
                if expiring:
                    logger.warning(f"发现 {len(expiring)} 个即将过期的密钥")
                    
                    if args.auto_rotate:
                        logger.info("自动轮换过期密钥...")
                        self.key_rotator.rotate_all_keys(days_before_expiry=args.days or 3)
                
                # 检查使用频率
                with self.key_manager.get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT key_id, COUNT(*) as usage_count
                        FROM usage_logs
                        WHERE timestamp > datetime('now', '-1 day')
                        GROUP BY key_id
                    ''')
                    
                    for row in cursor.fetchall():
                        if row['usage_count'] < 10:
                            logger.info(f"密钥 {row['key_id']} 使用较少 ({row['usage_count']}次/天)")
                
                # 休眠
                time.sleep(args.interval or 3600)  # 默认1小时
                
            except KeyboardInterrupt:
                logger.info("监控停止")
                break
            except Exception as e:
                logger.error(f"监控错误: {e}")
                time.sleep(60)
    
    def _test_model(self, args):
        """测试模型访问"""
        logger.info(f"🧪 测试模型: {args.model}")
        
        # 获取可用密钥
        key = self.key_manager.get_active_key(model_id=args.model)
        if not key:
            logger.error("没有可用密钥")
            return
        
        logger.info(f"使用密钥: {key['key_name']}")
        
        # 测试API调用
        import requests
        
        headers = {
            "Authorization": f"Bearer {key['key_value']}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": args.model,
            "messages": [
                {"role": "user", "content": "Hello, who are you?"}
            ],
            "max_tokens": 100
        }
        
        try:
            response = requests.post(
                f"{self.model_selector.get_model_endpoint(args.model)}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                print("\n" + "="*60)
                print(f"✅ 测试成功!")
                print(f"响应: {result['choices'][0]['message']['content']}")
                print("="*60)
                
                # 记录使用
                self.key_manager.mark_key_used(
                    key['id'], 
                    model_id=args.model,
                    success=True,
                    tokens=result.get('usage', {}).get('total_tokens', 0)
                )
            else:
                logger.error(f"API错误: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"测试失败: {e}")
    
    def _auto_run(self, args):
        """自动运行模式"""
        logger.info("🤖 自动运行模式启动...")
        
        while True:
            try:
                # 1. 检查并轮换过期密钥
                logger.info("检查过期密钥...")
                self.key_rotator.rotate_all_keys(days_before_expiry=3)
                
                # 2. 检查密钥数量，如果不足则创建新密钥
                stats = self.key_manager.get_account_stats()
                if stats.get('active_keys', 0) < args.min_keys:
                    need = args.min_keys - stats.get('active_keys', 0)
                    logger.info(f"活跃密钥不足，需要创建 {need} 个新密钥")
                    self.key_rotator.create_new_keys(count=min(need, 5))
                
                # 3. 休眠
                logger.info(f"休眠 {args.interval} 秒...")
                time.sleep(args.interval or 3600)
                
            except KeyboardInterrupt:
                logger.info("自动运行停止")
                break
            except Exception as e:
                logger.error(f"自动运行错误: {e}")
                time.sleep(60)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='🥔 NVIDIA NIM全自动密钥轮换系统')
    
    # 全局参数
    parser.add_argument('--action', '-a', 
                       choices=['rotate', 'create', 'list', 'monitor', 'test', 'auto'],
                       default='auto', help='执行动作')
    
    # 轮换参数
    parser.add_argument('--all', action='store_true', help='轮换所有过期密钥')
    parser.add_argument('--key-id', type=int, help='指定密钥ID')
    parser.add_argument('--days', type=int, default=3, help='提前多少天轮换')
    
    # 创建参数
    parser.add_argument('--count', '-c', type=int, default=1, help='创建密钥数量')
    parser.add_argument('--types', '-t', help='模型类型，逗号分隔')
    
    # 列表参数
    parser.add_argument('--detail', '-d', action='store_true', help='显示详细信息')
    
    # 监控参数
    parser.add_argument('--interval', '-i', type=int, default=3600, help='监控间隔（秒）')
    parser.add_argument('--auto-rotate', action='store_true', help='自动轮换')
    
    # 测试参数
    parser.add_argument('--model', '-m', help='测试的模型ID')
    
    # 自动运行参数
    parser.add_argument('--min-keys', type=int, default=10, help='最小活跃密钥数')
    
    args = parser.parse_args()
    
    # 创建系统实例
    system = NIMKeyRotationSystem()
    
    # 运行
    system.run(args)


if __name__ == '__main__':
    main()
