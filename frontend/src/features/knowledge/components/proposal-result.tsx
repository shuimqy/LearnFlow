import { Markdown } from "@/components/markdown";
import type { ProposalProcessing } from "../types";

const decisions = {
  approve: "采纳建议",
  revise: "修正后采纳",
  reject: "不采纳",
  needs_evidence: "需要补充依据",
};
const bases = { source: "课件或历史引用", reasoning: "通用知识与推理", insufficient: "依据不足" };

export function ProposalResult({ result }: { result: ProposalProcessing }) {
  return (
    <section className="proposal-result" aria-label="模型意见与处理结果">
      <div className="proposal-result-heading">
        <strong>处理结果</strong>
        <span>{result.applied ? `已写入第 ${result.applied_version} 版` : "未修改知识"}</span>
      </div>
      <p>{result.message}</p>
      {result.opinion && (
        <>
          <h4>模型意见{result.verdict && <span> · {decisions[result.verdict]}</span>}</h4>
          <Markdown>{result.opinion}</Markdown>
        </>
      )}
      {result.reasons?.length ? (
        <ul>
          {result.reasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}
        </ul>
      ) : null}
      {result.changes?.length ? (
        <>
          <h4>{result.applied ? "本次修改" : "模型建议的修改"}</h4>
          <ul>
            {result.changes.map((change, index) => (
              <li key={index}>{change}</li>
            ))}
          </ul>
        </>
      ) : null}
      {result.evidence?.length ? (
        <div className="proposal-evidence">
          {result.evidence.map((evidence, index) => {
            const source = result.sources?.find((row) => row.source_key === evidence.source_key);
            return (
              <div key={index}>
                {source &&
                  (source.document_id ? (
                    <a
                      href={`/api/documents/${source.document_id}/file#page=${source.page_number}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {source.filename} · 第 {source.page_number} 页
                    </a>
                  ) : (
                    <span>
                      {source.filename} · 第 {source.page_number} 页（历史引用）
                    </span>
                  ))}
                <p>{evidence.observation}</p>
                {source && <p className="field-hint">{source.note}</p>}
              </div>
            );
          })}
        </div>
      ) : null}
      {result.warnings?.length ? (
        <div className="proposal-review-warnings">
          {result.warnings.map((warning, index) => (
            <p key={index}>{warning}</p>
          ))}
        </div>
      ) : null}
      {result.content && (
        <details>
          <summary>查看模型处理后的正文</summary>
          <Markdown>{result.content}</Markdown>
        </details>
      )}
      {result.model && (
        <p className="field-hint">
          模型：{result.model}
          {result.basis && ` · 判断依据：${bases[result.basis]}`}
        </p>
      )}
    </section>
  );
}
