package io.github.gscratchpad

import android.app.Application

class GscratchpadApp : Application() {
    val container: AppContainer by lazy { AppContainer(this) }
}
