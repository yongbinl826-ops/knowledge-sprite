package dev.knowledgeguide.sprite;

import android.content.Context;
import android.content.SharedPreferences;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** App-local bounded KV. A successful set means commit() reported success. */
@CapacitorPlugin(name = "DurableDeviceStore")
public final class DurableDeviceStorePlugin extends Plugin {
    private static final String STORE = "KnowledgeSpriteDevice";
    private static final String KEY_PREFIX = "knowledge-sprite.device.";
    private static final int MAX_KEY_CHARS = 256;
    private static final int MAX_VALUE_BYTES = 10 * 1024 * 1024;

    private SharedPreferences preferences() {
        return getContext().getSharedPreferences(STORE, Context.MODE_PRIVATE);
    }

    private String validatedKey(PluginCall call) {
        String key = call.getString("key");
        if (key == null || !key.startsWith(KEY_PREFIX) || key.length() <= KEY_PREFIX.length() ||
                key.length() > MAX_KEY_CHARS || key.chars().anyMatch(c -> c < 32 || c == 127)) {
            call.reject("本机记录键无效。", "device_storage_invalid_key");
            return null;
        }
        return key;
    }

    @PluginMethod
    public void get(PluginCall call) {
        final String key = validatedKey(call);
        if (key == null) return;
        // Reuse the Bridge's existing worker/lifecycle. No extra executor or UI IO.
        getBridge().execute(() -> {
            try {
                String value = preferences().getString(key, null);
                JSObject result = new JSObject();
                result.put("value", value == null ? JSONObject.NULL : value);
                call.resolve(result);
            } catch (RuntimeException error) {
                call.reject("暂时无法读取本机记录。", "device_storage_read_failed");
            }
        });
    }

    @PluginMethod
    public void set(PluginCall call) {
        final String key = validatedKey(call);
        if (key == null) return;
        final String value = call.getString("value");
        if (value == null || value.length() > MAX_VALUE_BYTES ||
                value.getBytes(StandardCharsets.UTF_8).length > MAX_VALUE_BYTES) {
            call.reject("本机记录过大或格式无效。", "device_storage_invalid_value");
            return;
        }
        getBridge().execute(() -> {
            try {
                // apply() resolves after RAM mutation and cannot confirm disk persistence.
                boolean committed = preferences().edit().putString(key, value).commit();
                if (!committed) {
                    call.reject("本机记录保存失败，请重试。", "device_storage_write_failed");
                    return;
                }
                JSObject result = new JSObject();
                result.put("committed", true);
                call.resolve(result);
            } catch (RuntimeException error) {
                call.reject("本机记录保存失败，请重试。", "device_storage_write_failed");
            }
        });
    }
}
