---
name: dev-shell-assistant
description: 强制AI在读取文件和处理文件时使用Git Bash执行命令，必要时借用Python。
---

# 强制规则（最高优先级）

## 绝对禁止事项

1. **绝对禁止使用任何内置的read工具**
2. **绝对禁止使用PowerShell和CMD**
3. **绝对禁止使用内置的文件查看功能**

# windows 开发环境助手

## 核心规则

**重要：本Skill规定AI在Windows环境下执行任何命令、脚本或操作时，不要使用内置read等工具，要遵循以下优先级：**

1. **首选**：Git Bash Shell脚本 (.sh, .bash)
2. **次选**：Python脚本 (仅当Shell无法满足需求时)
3. **禁止**：PowerShell和CMD

## 工具选择原则

### 何时使用Shell脚本

- 简单的文件操作
- 环境变量配置
- 进程管理
- 日志分析
- 调用Java/Maven/Gradle命令
- 基本的文本处理（grep, sed, awk）

### 何时使用Python（备用）

- 复杂的数据解析和转换
- JSON/XML处理
- 正则表达式匹配复杂模式
- 调用外部API
- 生成复杂报告
- 需要跨平台兼容的复杂逻辑
- Shell命令组合过于复杂时

## Python环境检查机制

**强制规则：在使用任何Python脚本之前，必须先检查Python环境是否已配置。**

### 环境检查命令

```bash
# 简单检查Python是否可用
command -v python3 &> /dev/null || command -v python &> /dev/null
```

## AI交互行为准则

### 1. 默认使用Shell脚本

当用户询问Java开发问题时，**优先提供Shell脚本解决方案**：

```bash
# 正确：使用Shell脚本
#!/bin/bash
# 功能：批量处理Java文件

for file in $(find . -name "*.java"); do
    echo "处理: $file"
    grep -n "TODO" "$file"
done
```

### 2. 需要复杂处理时检查Python

```bash
# 先检查Python环境
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "错误：Python环境未配置"
    echo "当前操作需要Python支持，操作停止"
    exit 1
fi

# Python环境存在，继续执行
python3 script.py
```

### 3. 环境检查失败时的响应模板

```
Python环境未配置

当前操作需要Python支持，但未检测到Python环境。
操作已停止。

如需继续，请配置Python环境后重新执行。
```

### 文件操作

```bash
# 查找Java文件
find . -name "*.java"

# 统计代码行数
find . -name "*.java" | xargs wc -l

# 搜索代码内容
grep -r "TODO" --include="*.java" .
```

## 规则总结

1. **默认使用Git Bash Shell**：优先提供Shell方案
2. 不要使用自带 read 等工具。
3. **Python作为备用**：仅当Shell无法高效实现时使用
4. **强制环境检查**：使用Python前必须检查
5. **失败即停止**：Python不可用时停止并明确提示
6. **不提供下载链接**：只判断有无，不提供安装指导
7. **简洁反馈**：只说"Python环境未配置，操作停止"
8. **禁止PowerShell**：绝不使用PowerShell命令
9. **统一路径格式**：使用Unix风格路径（/c/xxx）
