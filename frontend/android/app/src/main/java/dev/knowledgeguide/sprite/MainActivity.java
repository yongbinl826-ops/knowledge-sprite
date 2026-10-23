package dev.knowledgeguide.sprite;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Capacitor 8.5.3 super.onCreate() creates the Bridge already. Register
        // with its builder first, before the local plugin list is consumed.
        registerPlugin(DurableDeviceStorePlugin.class);
        super.onCreate(savedInstanceState);
    }
}
