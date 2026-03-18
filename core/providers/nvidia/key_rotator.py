# providers/nvidia/key_rotator.py
import time
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from core.key_manager import KeyManager
from core.pool_manager import pool_manager
from core.browser_manager import BitBrowserManager

logger = logging.getLogger(__name__)

class NVIDIAKeyRotator:
    """NVIDIA API密钥轮换器"""
    
    def __init__(self, config: Dict, key_manager: KeyManager):
        self.config = config
        self.key_manager = key_manager
        self.browser_manager = BitBrowserManager(config)
        
    def rotate_all_keys(self, days_before_expiry: int = 3):
        """轮换所有即将过期的密钥 [citation:3]"""
        logger.info("开始检查并轮换即将过期的密钥...")
        
        # 获取即将过期的密钥
        expiring_keys = self.key_manager.get_expiring_keys(days=days_before_expiry)
        
        for key in expiring_keys:
            try:
                logger.info(f"轮换密钥: {key['key_name']} (过期时间: {key['expires_at']})")
                
                # 为每个密钥创建独立的浏览器环境
                browser_env = self.browser_manager.create_environment()
                
                # 登录NGC并轮换密钥
                new_key = self._rotate_single_key(browser_env, key)
                
                if new_key:
                    # 停用旧密钥
                    self.key_manager.deactivate_key(
                        key['id'], 
                        f"已轮换为新密钥 {new_key['key_name']}"
                    )
                    
                    # 添加新密钥
                    self.key_manager.add_api_key(
                        account_id=key['account_id'],
                        key_name=new_key['name'],
                        key_value=new_key['value'],
                        key_id=new_key['id'],
                        services=new_key.get('services'),
                        expires_at=datetime.now() + timedelta(days=30)
                    )
                    
                    logger.info(f"✅ 密钥轮换成功: {key['key_name']} -> {new_key['name']}")
                
                # 清理环境
                self.browser_manager.destroy_environment(browser_env['browser_id'])
                
                # 避免请求过快
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"轮换密钥失败 {key['key_name']}: {e}")
    
    def _rotate_single_key(self, browser_env: Dict, old_key: Dict) -> Optional[Dict]:
        """在NGC中轮换单个密钥 [citation:3]"""
        try:
            driver = browser_env['driver']
            wait = WebDriverWait(driver, 20)
            
            # 1. 登录NGC
            driver.get("https://org.ngc.nvidia.com/login")
            
            # 使用账号密码登录
            email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
            email_input.send_keys(old_key['email'])
            
            password_input = driver.find_element(By.NAME, "password")
            password_input.send_keys(self._get_account_password(old_key['account_id']))
            
            login_btn = driver.find_element(By.XPATH, "//button[@type='submit']")
            login_btn.click()
            
            # 等待登录完成
            time.sleep(5)
            
            # 2. 进入API密钥页面 [citation:3]
            driver.get("https://org.ngc.nvidia.com/setup/api-keys")
            time.sleep(3)
            
            # 3. 找到旧密钥并点击轮换
            key_rows = driver.find_elements(By.XPATH, "//tr[contains(., '{}')]".format(old_key['key_name']))
            if key_rows:
                rotate_btn = key_rows[0].find_element(By.XPATH, ".//button[contains(text(), 'Rotate')]")
                rotate_btn.click()
                time.sleep(2)
                
                # 确认轮换
                confirm_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(text(), 'Confirm')]")
                ))
                confirm_btn.click()
                time.sleep(3)
                
                # 4. 获取新密钥
                new_key_element = wait.until(EC.presence_of_element_located(
                    (By.XPATH, "//div[contains(@class, 'api-key-value')]")
                ))
                new_key_value = new_key_element.text
                
                # 获取密钥名称
                key_name_input = driver.find_element(By.NAME, "keyName")
                new_key_name = key_name_input.get_attribute("value")
                
                # 获取密钥ID
                key_id_element = driver.find_element(By.XPATH, "//div[contains(text(), 'Key ID:')]")
                key_id = key_id_element.text.replace("Key ID:", "").strip()
                
                return {
                    'name': new_key_name,
                    'value': new_key_value,
                    'id': key_id,
                    'services': 'NGC Catalog, Public API Endpoints'
                }
            
        except Exception as e:
            logger.error(f"轮换操作失败: {e}")
            return None
    
    def _get_account_password(self, account_id: int) -> str:
        """获取账号密码"""
        with self.key_manager.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT password FROM accounts WHERE id = ?', (account_id,))
            row = cursor.fetchone()
            return row['password'] if row else None
    
    def create_new_keys(self, count: int = 1, model_types: List[str] = None):
        """创建新的API密钥 [citation:3]"""
        logger.info(f"开始创建 {count} 个新密钥...")
        
        for i in range(count):
            try:
                # 创建新账号
                account = self._create_new_account()
                if not account:
                    logger.error("创建账号失败")
                    continue
                
                # 为账号生成API密钥
                keys = self._generate_api_keys(account, model_types)
                
                logger.info(f"✅ 创建 {len(keys)} 个密钥成功")
                
                # 避免请求过快
                time.sleep(10)
                
            except Exception as e:
                logger.error(f"创建密钥失败: {e}")
    
    def _create_new_account(self) -> Optional[Dict]:
        """创建新的NGC账号"""
        browser_env = None
        try:
            # 创建浏览器环境
            browser_env = self.browser_manager.create_environment()
            driver = browser_env['driver']
            wait = WebDriverWait(driver, 20)
            
            # 获取临时邮箱
            email_info = pool_manager.get_email()
            
            # 访问NGC注册页面
            driver.get("https://org.ngc.nvidia.com/signup")
            time.sleep(3)
            
            # 填写注册表单
            email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
            email_input.send_keys(email_info['email'])
            
            # 生成密码
            import random
            import string
            password = ''.join(random.choices(
                string.ascii_letters + string.digits + "!@#$%", 
                k=16
            ))
            
            password_input = driver.find_element(By.NAME, "password")
            password_input.send_keys(password)
            
            confirm_password = driver.find_element(By.NAME, "confirmPassword")
            confirm_password.send_keys(password)
            
            # 勾选同意条款
            terms_checkbox = driver.find_element(By.XPATH, "//input[@type='checkbox']")
            terms_checkbox.click()
            
            # 提交注册
            submit_btn = driver.find_element(By.XPATH, "//button[@type='submit']")
            submit_btn.click()
            
            # 等待验证邮件
            time.sleep(10)
            
            # 从邮箱获取验证链接
            verification_link = pool_manager.get_email_verification(email_info)
            if verification_link:
                driver.get(verification_link)
                time.sleep(3)
            
            # 注册成功
            account_info = {
                'email': email_info['email'],
                'password': password,
                'ngc_username': email_info['email'].split('@')[0],
                'created_at': datetime.now()
            }
            
            # 保存到数据库
            account_id = self.key_manager.add_account(
                email=account_info['email'],
                password=account_info['password'],
                ngc_username=account_info['ngc_username']
            )
            account_info['id'] = account_id
            
            return account_info
            
        except Exception as e:
            logger.error(f"创建账号失败: {e}")
            return None
            
        finally:
            if browser_env:
                self.browser_manager.destroy_environment(browser_env['browser_id'])
    
    def _generate_api_keys(self, account: Dict, model_types: List[str] = None) -> List[Dict]:
        """为账号生成API密钥 [citation:3]"""
        browser_env = None
        keys = []
        
        try:
            browser_env = self.browser_manager.create_environment()
            driver = browser_env['driver']
            wait = WebDriverWait(driver, 20)
            
            # 登录NGC
            driver.get("https://org.ngc.nvidia.com/login")
            
            email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
            email_input.send_keys(account['email'])
            
            password_input = driver.find_element(By.NAME, "password")
            password_input.send_keys(account['password'])
            
            login_btn = driver.find_element(By.XPATH, "//button[@type='submit']")
            login_btn.click()
            time.sleep(5)
            
            # 进入API密钥页面
            driver.get("https://org.ngc.nvidia.com/setup/api-keys")
            time.sleep(3)
            
            # 生成多个密钥
            max_keys = self.config['key_management']['max_keys_per_account']
            for i in range(min(max_keys, 5)):
                # 点击生成密钥
                generate_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(text(), 'Generate Personal Key')]")
                ))
                generate_btn.click()
                time.sleep(2)
                
                # 输入密钥名称
                key_name = f"auto_key_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i}"
                name_input = wait.until(EC.presence_of_element_located((By.NAME, "keyName")))
                name_input.clear()
                name_input.send_keys(key_name)
                
                # 选择服务 [citation:3]
                services_dropdown = driver.find_element(By.XPATH, "//select[contains(@name, 'services')]")
                services_dropdown.click()
                
                # 选择NGC Catalog
                ngc_option = driver.find_element(By.XPATH, "//option[contains(text(), 'NGC Catalog')]")
                ngc_option.click()
                
                # 选择Public API Endpoints
                api_option = driver.find_element(By.XPATH, "//option[contains(text(), 'Public API Endpoints')]")
                api_option.click()
                
                # 设置过期时间（30天）
                expiry_select = driver.find_element(By.NAME, "expiration")
                expiry_select.click()
                thirty_days = driver.find_element(By.XPATH, "//option[contains(text(), '30 days')]")
                thirty_days.click()
                
                # 生成密钥
                generate_confirm = driver.find_element(By.XPATH, "//button[contains(text(), 'Generate')]")
                generate_confirm.click()
                time.sleep(3)
                
                # 获取生成的密钥
                key_element = wait.until(EC.presence_of_element_located(
                    (By.XPATH, "//div[contains(@class, 'api-key-value')]")
                ))
                key_value = key_element.text
                
                # 获取密钥ID
                key_id_element = driver.find_element(By.XPATH, "//div[contains(text(), 'Key ID:')]")
                key_id = key_id_element.text.replace("Key ID:", "").strip()
                
                # 保存密钥
                key_info = {
                    'account_id': account['id'],
                    'key_name': key_name,
                    'key_value': key_value,
                    'key_id': key_id,
                    'services': 'NGC Catalog, Public API Endpoints',
                    'expires_at': datetime.now() + timedelta(days=30)
                }
                
                key_db_id = self.key_manager.add_api_key(**key_info)
                key_info['db_id'] = key_db_id
                keys.append(key_info)
                
                logger.info(f"✅ 生成密钥: {key_name}")
                
                # 返回密钥列表页
                driver.back()
                time.sleep(2)
            
            return keys
            
        except Exception as e:
            logger.error(f"生成密钥失败: {e}")
            return keys
            
        finally:
            if browser_env:
                self.browser_manager.destroy_environment(browser_env['browser_id'])
