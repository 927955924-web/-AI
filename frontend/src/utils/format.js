import dayjs from 'dayjs'

/**
 * Format date to readable string
 */
export function formatDate(date, format = 'YYYY-MM-DD HH:mm') {
  if (!date) return ''
  return dayjs(date).format(format)
}

/**
 * Format date to relative time
 */
export function formatRelativeTime(date) {
  if (!date) return ''
  const now = dayjs()
  const target = dayjs(date)
  const diffMinutes = now.diff(target, 'minute')
  
  if (diffMinutes < 1) return '刚刚'
  if (diffMinutes < 60) return `${diffMinutes}分钟前`
  
  const diffHours = now.diff(target, 'hour')
  if (diffHours < 24) return `${diffHours}小时前`
  
  const diffDays = now.diff(target, 'day')
  if (diffDays < 30) return `${diffDays}天前`
  
  return formatDate(date, 'YYYY-MM-DD')
}

/**
 * Format price to currency string
 */
export function formatPrice(price, currency = '¥') {
  if (price === null || price === undefined) return ''
  return `${currency}${Number(price).toFixed(2)}`
}

/**
 * Truncate text with ellipsis
 */
export function truncate(text, length = 50) {
  if (!text) return ''
  if (text.length <= length) return text
  return text.slice(0, length) + '...'
}

/**
 * Copy text to clipboard
 */
export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch (e) {
    // Fallback for older browsers
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const success = document.execCommand('copy')
    document.body.removeChild(textarea)
    return success
  }
}

/**
 * Debounce function
 */
export function debounce(fn, delay = 300) {
  let timer = null
  return function (...args) {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => fn.apply(this, args), delay)
  }
}

/**
 * Parse phone number validation
 */
export function isValidPhone(phone) {
  return /^1[3-9]\d{9}$/.test(phone)
}
