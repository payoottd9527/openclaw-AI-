# config.py
import os
from datetime import timedelta

# ================== NVIDIA NIM 配置 ==================
NVIDIA_CONFIG = {
    'api': {
        'base_url': 'https://integrate.api.nvidia.com/v1',
        'ngc_url': 'https://org.ngc.nvidia.com',
        'api_key_url': 'https://org.ngc.nvidia.com/setup/api-keys',
        'timeout': 30,
        'max_retries': 3
    },
    
    # 账号注册配置 [citation:1][citation:3]
    'registration': {
        'email_domains': ['tempmail.com', '10minutemail.com', 'guerrillamail.com'],
        'password_length': 16,
        'password_complexity': 'high',  # 大小写+数字+特殊字符
        'require_phone': False,
        'require_company': True,
        'services_included': ['NGC Catalog', 'Public API Endpoints']  # API密钥需要的服务 [citation:3]
    },
    
    # 密钥管理 [citation:3]
    'key_management': {
        'auto_rotate': True,
        'rotation_interval': timedelta(days=7),  # 每7天轮换一次
        'max_keys_per_account': 5,  # 每个账号最多5个密钥
        'key_expiration': timedelta(days=30),  # 密钥有效期30天
        'pre_rotate_days': 3  # 过期前3天提前轮换
    },
    
    # 模型选择
    'model_selection': {
        'strategy': 'round_robin',  # round_robin, random, least_used
        'preferred_types': ['text-generation', 'reasoning', 'vision-language'],
        'min_gpu_memory': 24,  # 最低GPU内存要求
        'exclude_models': []  # 排除的模型
    },
    
    # NGC认证 [citation:1][citation:5]
    'ngc_auth': {
        'username': '$oauthtoken',  # NGC特殊用户名
        'docker_registry': 'nvcr.io',
        'cache_dir': '~/.cache/nim'  # 模型缓存目录 [citation:5]
    }
}

# ================== 虚拟池配置 ==================
# 复用之前的池配置，添加NVIDIA特定配置
POOL_CONFIG = {
    'email': {
        'enabled': True,
        'providers': ['temp_mail', 'guerrilla', 'mail_tm'],
        'pool_size': 50,
        'max_usage_per_email': 2
    },
    'phone': {
        'enabled': False,  # NVIDIA可能不需要手机验证
        'providers': ['tpn', 'vnu'],
        'pool_size': 20
    },
    'browser': {
        'profiles_dir': './data/profiles',
        'max_concurrent': 10,
        'fingerprint_rotation': True
    }
}

# ================== 数据库配置 ==================
DATABASE_CONFIG = {
    'keys_db': './data/keys.db',
    'accounts_db': './data/accounts.db',
    'backup_dir': './data/backups',
    'auto_backup': True,
    'backup_interval': timedelta(days=1)
}

# ================== 日志配置 ==================
LOG_CONFIG = {
    'level': 'INFO',
    'file': './logs/key_rotator.log',
    'max_size': 10 * 1024 * 1024,  # 10MB
    'backup_count': 5,
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
}
