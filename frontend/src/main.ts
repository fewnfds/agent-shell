import { createApp } from 'vue'
import '@adminlte/vue/css'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import 'bootstrap/js/dist/dropdown'
import 'bootstrap-icons/font/bootstrap-icons.css'

import App from './App.vue'
import { i18n } from './locales'
import { router } from './router'
import './styles/management-console.css'

createApp(App).use(router).use(i18n).mount('#app')
