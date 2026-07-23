export function useTheme() {
  const KEY = 'agent-studio-theme'

  function get(): 'light' | 'dark' {
    const stored = localStorage.getItem(KEY)
    if (stored === 'dark' || stored === 'light') return stored
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }

  function apply(theme: 'light' | 'dark') {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem(KEY, theme)
    const meta = document.querySelector('meta[name="color-scheme"]')
    if (meta) meta.setAttribute('content', theme)
  }

  function toggle() {
    const next = get() === 'dark' ? 'light' : 'dark'
    apply(next)
    return next
  }

  // Initialize on load
  apply(get())

  return { get, apply, toggle }
}
