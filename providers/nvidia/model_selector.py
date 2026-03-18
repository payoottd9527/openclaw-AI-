# providers/nvidia/model_selector.py
import json
import random
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class ModelSelector:
    """NVIDIA NIM模型选择器"""
    
    def __init__(self, models_file: str, key_manager, config: Dict):
        with open(models_file, 'r') as f:
            self.models = json.load(f)['models']
        
        self.key_manager = key_manager
        self.config = config
        self.strategy = config['model_selection']['strategy']
        
    def get_all_models(self) -> List[Dict]:
        """获取所有模型"""
        return self.models
    
    def get_models_by_type(self, model_type: str) -> List[Dict]:
        """按类型获取模型"""
        return [m for m in self.models if m['type'] == model_type]
    
    def get_models_by_gpu(self, min_gpu_memory: int) -> List[Dict]:
        """按GPU要求获取模型"""
        return [m for m in self.models if m['min_gpu_memory'] <= min_gpu_memory]
    
    def select_model_for_key(self, key_id: int = None) -> Optional[Dict]:
        """为特定密钥选择模型"""
        if self.strategy == 'round_robin':
            return self._round_robin_select(key_id)
        elif self.strategy == 'random':
            return self._random_select(key_id)
        elif self.strategy == 'least_used':
            return self._least_used_select(key_id)
        else:
            return self._random_select(key_id)
    
    def _round_robin_select(self, key_id: int = None) -> Optional[Dict]:
        """轮询选择"""
        if not self.models:
            return None
        
        # 获取密钥的最后使用记录
        last_used_model = None
        if key_id:
            with self.key_manager.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT model_id FROM model_access 
                    WHERE key_id = ? 
                    ORDER BY last_access DESC LIMIT 1
                ''', (key_id,))
                row = cursor.fetchone()
                if row:
                    last_used_model = row['model_id']
        
        # 找到下一个模型
        if last_used_model:
            for i, model in enumerate(self.models):
                if model['id'] == last_used_model:
                    next_index = (i + 1) % len(self.models)
                    return self.models[next_index]
        
        return self.models[0]
    
    def _random_select(self, key_id: int = None) -> Optional[Dict]:
        """随机选择"""
        if not self.models:
            return None
        return random.choice(self.models)
    
    def _least_used_select(self, key_id: int = None) -> Optional[Dict]:
        """选择使用最少的模型"""
        if not self.models:
            return None
        
        # 获取模型使用次数
        usage_counts = {}
        with self.key_manager.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT model_id, SUM(access_count) as total_usage
                FROM model_access
                WHERE key_id = ?
                GROUP BY model_id
            ''', (key_id,))
            
            for row in cursor.fetchall():
                usage_counts[row['model_id']] = row['total_usage']
        
        # 找出使用最少的模型
        min_usage = float('inf')
        selected_model = None
        
        for model in self.models:
            usage = usage_counts.get(model['id'], 0)
            if usage < min_usage:
                min_usage = usage
                selected_model = model
        
        return selected_model or random.choice(self.models)
    
    def get_model_endpoint(self, model_id: str) -> str:
        """获取模型API端点"""
        for model in self.models:
            if model['id'] == model_id:
                return model.get('api_base', 'https://integrate.api.nvidia.com/v1')
        return 'https://integrate.api.nvidia.com/v1'
    
    def filter_models(self, model_types: List[str] = None, 
                      min_gpu: int = None, exclude: List[str] = None) -> List[Dict]:
        """过滤模型"""
        filtered = self.models.copy()
        
        if model_types:
            filtered = [m for m in filtered if m['type'] in model_types]
        
        if min_gpu:
            filtered = [m for m in filtered if m['min_gpu_memory'] <= min_gpu]
        
        if exclude:
            filtered = [m for m in filtered if m['id'] not in exclude]
        
        return filtered
