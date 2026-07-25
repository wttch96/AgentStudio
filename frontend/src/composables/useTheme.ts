import { ref } from 'vue'

const KEY = 'agent-studio-theme'

function getStored(): 'light' | 'dark' {
  const stored = localStorage.getItem(KEY)
  if (stored === 'dark' || stored === 'light') return stored
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function apply(theme: 'light' | 'dark') {
  // Element Plus dark mode
  document.documentElement.classList.toggle('dark', theme === 'dark')
  // Legacy CSS compatibility
  document.documentElement.setAttribute('data-theme', theme)
  // Color scheme meta
  const meta = document.querySelector('meta[name="color-scheme"]')
  if (meta) meta.setAttribute('content', theme === 'dark' ? 'dark' : 'light')
  else {
    const m = document.createElement('meta')
    m.name = 'color-scheme'; m.content = theme === 'dark' ? 'dark' : 'light'
    document.head.appendChild(m)
  }
  localStorage.setItem(KEY, theme)
}

const current = ref<'light' | 'dark'>(getStored())
apply(current.value)

export function useTheme() {
  function toggle() {
    current.value = current.value === 'dark' ? 'light' : 'dark'
    apply(current.value)
  }
  function set(theme: 'light' | 'dark') {
    current.value = theme
    apply(theme)
  }
  return { current, toggle, set }
}
