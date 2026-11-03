import threading
from contextlib import contextmanager

from fastapi import HTTPException
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


def thread_id(user_id, course_id, conversation_id):
    return f"user:{user_id}:course:{course_id}:chat:{conversation_id}"


class OwnedPostgresSaver(PostgresSaver):
    def __init__(self, connection, identity, run_id):
        super().__init__(connection, serde=JsonPlusSerializer(pickle_fallback=False))
        self.identity, self.run_id = identity, run_id
        self.write_lock = threading.Lock()

    @contextmanager
    def current_run(self):
        # 与切换运行标识、删除会话互斥，迟到的旧请求不能覆盖新 checkpoint。
        with self.write_lock, self.conn.transaction():
            row = self.conn.execute(
                "SELECT run_id FROM chat_graph_threads WHERE thread_id = %s FOR SHARE",
                (self.identity,),
            ).fetchone()
            if not row:
                raise HTTPException(404, "对话已删除")
            if row[0] != self.run_id:
                raise HTTPException(409, "这次回答请求已失效，请查看最新对话")
            yield

    def put(self, config, checkpoint, metadata, new_versions):
        with self.current_run():
            return super().put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):
        safe = [
            (channel, "回答节点执行失败，可从消息记录重试。" if channel == "__error__" else value)
            for channel, value in writes
        ]
        with self.current_run():
            return super().put_writes(config, safe, task_id, task_path)


@contextmanager
def conversation_checkpointer(db, identity, run_id):
    if db.get_bind().dialect.name != "postgresql":
        raise RuntimeError("LangGraph checkpoints require PostgreSQL.")
    # checkpoint 使用独立连接，模型调用期间不占用知识修订的事务或行锁。
    with db.get_bind().connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        yield OwnedPostgresSaver(connection.connection.driver_connection, identity, run_id)
