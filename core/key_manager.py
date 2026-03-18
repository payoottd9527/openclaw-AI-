# core/key_manager.py
import os
import json
import time
import sqlite3
import hashlib
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import logging
from threading import Lock
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class KeyManager:
    """NVIDIA NIM密钥管理器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = Lock()
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        with self.get_db() as conn:
            cursor = conn.cursor()
            
            # 账号表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE,
                    password TEXT,
                    ngc_username TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP,
                    last_used TIMESTAMP,
                    total_keys INTEGER DEFAULT 0,
                    notes TEXT
                )
            ''')
            
            # 密钥表 [citation:3]
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    key_name TEXT,
                    key_value TEXT UNIQUE,
                    key_id TEXT,  -- NGC中的密钥ID
                    services TEXT,  -- 包含的服务
                    created_at TIMESTAMP,
                    expires_at TIMESTAMP,
                    last_used TIMESTAMP,
                    usage_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    model_access TEXT,  -- 可访问的模型列表
                    notes TEXT,
                    FOREIGN KEY (account_id) REFERENCES accounts(id)
                )
            ''')
            
            # 模型访问表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS model_access (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id INTEGER,
                    model_id TEXT,
                    access_count INTEGER DEFAULT 0,
                    last_access TIMESTAMP,
                    success_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    FOREIGN KEY (key_id) REFERENCES api_keys(id)
                )
            ''')
            
            # 使用日志表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id INTEGER,
                    model_id TEXT,
                    timestamp TIMESTAMP,
                    success BOOLEAN,
                    response_time FLOAT,
                    error_message TEXT,
                    tokens_used INTEGER,
                    FOREIGN KEY (key_id) REFERENCES api_keys(id)
                )
            ''')
            
            conn.commit()
    
    @contextmanager
    def get_db(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def add_account(self, email: str, password: str, ngc_username: str = None) -> int:
        """添加账号"""
        with self.lock:
            with self.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO accounts (email, password, ngc_username, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (email, password, ngc_username, datetime.now()))
                conn.commit()
                return cursor.lastrowid
    
    def add_api_key(self, account_id: int, key_name: str, key_value: str, 
                    key_id: str = None, services: str = None, 
                    expires_at: datetime = None) -> int:
        """添加API密钥 [citation:3]"""
        with self.lock:
            with self.get_db() as conn:
                cursor = conn.cursor()
                
                # 检查是否已存在
                cursor.execute('SELECT id FROM api_keys WHERE key_value = ?', (key_value,))
                if cursor.fetchone():
                    logger.warning(f"密钥已存在: {key_name}")
                    return None
                
                # 插入新密钥
                cursor.execute('''
                    INSERT INTO api_keys 
                    (account_id, key_name, key_value, key_id, services, created_at, expires_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    account_id, key_name, key_value, key_id, services,
                    datetime.now(), expires_at or datetime.now() + timedelta(days=30),
                    'active'
                ))
                
                # 更新账号的密钥计数
                cursor.execute('''
                    UPDATE accounts SET total_keys = total_keys + 1, last_used = ?
                    WHERE id = ?
                ''', (datetime.now(), account_id))
                
                conn.commit()
                return cursor.lastrowid
    
    def get_active_key(self, model_id: str = None, 
                      preferred_accounts: List[int] = None) -> Optional[Dict]:
        """获取可用的密钥"""
        with self.get_db() as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT k.*, a.email, a.ngc_username 
                FROM api_keys k
                JOIN accounts a ON k.account_id = a.id
                WHERE k.status = 'active'
                AND (k.expires_at IS NULL OR k.expires_at > ?)
            '''
            params = [datetime.now()]
            
            if model_id:
                # 检查密钥是否有该模型的访问权限
                query += '''
                    AND (k.model_access IS NULL OR 
                         json_extract(k.model_access, '$') IS NULL OR
                         k.model_access LIKE ?)
                '''
                params.append(f'%{model_id}%')
            
            if preferred_accounts:
                placeholders = ','.join(['?'] * len(preferred_accounts))
                query += f' AND k.account_id IN ({placeholders})'
                params.extend(preferred_accounts)
            
            query += ' ORDER BY k.last_used ASC, k.usage_count ASC LIMIT 1'
            
            cursor.execute(query, params)
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return None
    
    def mark_key_used(self, key_id: int, model_id: str = None, 
                      success: bool = True, tokens: int = 0):
        """标记密钥已使用"""
        with self.lock:
            with self.get_db() as conn:
                cursor = conn.cursor()
                
                # 更新密钥使用计数
                cursor.execute('''
                    UPDATE api_keys 
                    SET last_used = ?, usage_count = usage_count + 1
                    WHERE id = ?
                ''', (datetime.now(), key_id))
                
                # 记录使用日志
                if model_id:
                    cursor.execute('''
                        INSERT INTO usage_logs 
                        (key_id, model_id, timestamp, success, tokens_used)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (key_id, model_id, datetime.now(), success, tokens))
                    
                    # 更新模型访问统计
                    cursor.execute('''
                        INSERT INTO model_access (key_id, model_id, last_access, access_count)
                        VALUES (?, ?, ?, 1)
                        ON CONFLICT(key_id, model_id) DO UPDATE SET
                            access_count = access_count + 1,
                            last_access = excluded.last_access,
                            success_count = success_count + ?,
                            error_count = error_count + ?
                    ''', (key_id, model_id, datetime.now(), 
                          1 if success else 0, 0 if success else 1))
                
                conn.commit()
    
    def get_keys_by_model(self, model_id: str) -> List[Dict]:
        """获取能访问特定模型的所有密钥"""
        with self.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT k.*, a.email, a.ngc_username 
                FROM api_keys k
                JOIN accounts a ON k.account_id = a.id
                WHERE k.status = 'active'
                AND (k.expires_at IS NULL OR k.expires_at > ?)
                AND (k.model_access IS NULL OR k.model_access LIKE ?)
                ORDER BY k.last_used ASC
            ''', (datetime.now(), f'%{model_id}%'))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_expiring_keys(self, days: int = 7) -> List[Dict]:
        """获取即将过期的密钥"""
        with self.get_db() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now() + timedelta(days=days)
            cursor.execute('''
                SELECT k.*, a.email, a.ngc_username 
                FROM api_keys k
                JOIN accounts a ON k.account_id = a.id
                WHERE k.status = 'active'
                AND k.expires_at IS NOT NULL
                AND k.expires_at <= ?
                ORDER BY k.expires_at ASC
            ''', (cutoff,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def deactivate_key(self, key_id: int, reason: str = None):
        """停用密钥"""
        with self.lock:
            with self.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE api_keys 
                    SET status = 'inactive', notes = ?
                    WHERE id = ?
                ''', (reason, key_id))
                conn.commit()
    
    def get_account_stats(self, account_id: int = None) -> Dict:
        """获取账号统计信息"""
        with self.get_db() as conn:
            cursor = conn.cursor()
            
            if account_id:
                cursor.execute('''
                    SELECT 
                        COUNT(DISTINCT k.id) as total_keys,
                        SUM(CASE WHEN k.status = 'active' THEN 1 ELSE 0 END) as active_keys,
                        SUM(CASE WHEN k.expires_at <= ? THEN 1 ELSE 0 END) as expired_keys,
                        SUM(k.usage_count) as total_usage,
                        MAX(k.last_used) as last_used
                    FROM api_keys k
                    WHERE k.account_id = ?
                ''', (datetime.now(), account_id))
            else:
                cursor.execute('''
                    SELECT 
                        COUNT(DISTINCT a.id) as total_accounts,
                        COUNT(DISTINCT k.id) as total_keys,
                        SUM(CASE WHEN k.status = 'active' THEN 1 ELSE 0 END) as active_keys,
                        SUM(CASE WHEN k.expires_at <= ? THEN 1 ELSE 0 END) as expired_keys,
                        SUM(k.usage_count) as total_usage
                    FROM accounts a
                    LEFT JOIN api_keys k ON a.id = k.account_id
                ''', (datetime.now(),))
            
            return dict(cursor.fetchone())
