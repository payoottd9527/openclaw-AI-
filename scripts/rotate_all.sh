#!/bin/bash

# 🥔 小土豆NIM密钥自动轮换脚本

echo "🥔 开始自动轮换NIM密钥..."

# 配置
LOG_DIR="./logs"
mkdir -p $LOG_DIR

# 轮换所有过期密钥
python main.py --action rotate --all --days 3

# 检查密钥数量，如果不足则创建
KEY_COUNT=$(python main.py --action list | grep "活跃密钥" | awk '{print $3}')
if [ $KEY_COUNT -lt 20 ]; then
    NEED=$((20 - KEY_COUNT))
    echo "活跃密钥不足，创建 $NEED 个新密钥"
    python main.py --action create --count $NEED
fi

# 记录日志
echo "$(date): 轮换完成，当前活跃密钥: $KEY_COUNT" >> $LOG_DIR/rotate.log

echo "✅ 轮换完成"
