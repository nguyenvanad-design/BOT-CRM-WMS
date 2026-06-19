/**
 * Tokinarc frontend — src/lib/useDebounced.ts
 * Trả về giá trị debounce sau `ms`. `onChange` (tùy chọn) gọi mỗi khi giá trị
 * debounce đổi — tiện để reset trang về 1 khi đổi từ khóa tìm kiếm.
 */
import { useEffect, useRef, useState } from 'react'

export function useDebounced<T>(value: T, ms: number, onChange?: (v: T) => void): T {
  const [debounced, setDebounced] = useState(value)
  const cbRef = useRef(onChange)
  cbRef.current = onChange

  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced(value)
      cbRef.current?.(value)
    }, ms)
    return () => clearTimeout(t)
  }, [value, ms])

  return debounced
}
