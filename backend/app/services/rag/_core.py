"""
知识库存储。

使用 deepseek-v4-pro 模型进行向量化，并使用 sqlite-vec 进行向量相似度搜索。

使用 RecursiveCharacterTextSplitter 将文本分割为 500 字符的块，重叠 50 字符。

"""
from langchain_openai import OpenAIEmbeddings


class KnowledgeStore:
    #
    embeddings: OpenAIEmbeddings

    def __init(self):
