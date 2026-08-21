import { config } from '@vue/test-utils'
import { defineComponent } from 'vue'

const TeleportStub = defineComponent({
  name: 'TeleportStub',
  props: {
    disabled: Boolean,
    to: {
      type: [String, Object],
      required: true,
    },
  },
  setup(_, { slots }) {
    return () => slots.default?.()
  },
})

config.global.stubs = { Teleport: TeleportStub }
