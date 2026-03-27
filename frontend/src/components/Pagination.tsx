import { useEffect, useMemo, useState } from "react";

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  pageSizeOptions?: number[];
}

function buildPageNumbers(page: number, totalPages: number): number[] {
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }
  if (page <= 3) {
    return [1, 2, 3, 4, 5];
  }
  if (page >= totalPages - 2) {
    return [
      totalPages - 4,
      totalPages - 3,
      totalPages - 2,
      totalPages - 1,
      totalPages,
    ];
  }
  return [page - 2, page - 1, page, page + 1, page + 2];
}

export function Pagination(props: PaginationProps) {
  const { page, pageSize, total, onPageChange, onPageSizeChange } = props;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const pageNumbers = useMemo(() => buildPageNumbers(page, totalPages), [page, totalPages]);
  const [jumpValue, setJumpValue] = useState(String(page));

  useEffect(() => {
    setJumpValue(String(page));
  }, [page]);

  const jumpToPage = () => {
    const nextPage = Number(jumpValue);
    if (!Number.isInteger(nextPage)) {
      setJumpValue(String(page));
      return;
    }
    const normalized = Math.min(Math.max(nextPage, 1), totalPages);
    onPageChange(normalized);
  };

  return (
    <div className="pagination-bar">
      <p className="pagination-info">
        共 {total} 条，第 {page}/{totalPages} 页
      </p>
      <div className="pagination-actions">
        <label className="pagination-size">
          每页
          <select
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
            value={pageSize}
          >
            {(props.pageSizeOptions || [10, 20, 50, 100]).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          条
        </label>

        <div className="pagination-pages">
          <button
            className="ghost-btn small"
            disabled={page <= 1}
            onClick={() => onPageChange(1)}
            type="button"
          >
            首页
          </button>
          <button
            className="ghost-btn small"
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
            type="button"
          >
            上一页
          </button>
          {pageNumbers.map((pageNumber) => (
            <button
              className={pageNumber === page ? "mode-btn active" : "mode-btn"}
              key={pageNumber}
              onClick={() => onPageChange(pageNumber)}
              type="button"
            >
              {pageNumber}
            </button>
          ))}
          <button
            className="ghost-btn small"
            disabled={page >= totalPages}
            onClick={() => onPageChange(page + 1)}
            type="button"
          >
            下一页
          </button>
          <button
            className="ghost-btn small"
            disabled={page >= totalPages}
            onClick={() => onPageChange(totalPages)}
            type="button"
          >
            末页
          </button>
        </div>

        <div className="pagination-jump">
          <span>跳转</span>
          <input
            inputMode="numeric"
            onChange={(event) => setJumpValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                jumpToPage();
              }
            }}
            value={jumpValue}
          />
          <button className="ghost-btn small" onClick={jumpToPage} type="button">
            前往
          </button>
        </div>
      </div>
    </div>
  );
}
