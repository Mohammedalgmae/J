package sa.countdown.dammam;
import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.graphics.Color;
public class MainActivity extends Activity {
 private WebView webView;
 @Override public void onCreate(Bundle state) {
  super.onCreate(state);
  getWindow().setStatusBarColor(Color.rgb(15,23,42));
  getWindow().setNavigationBarColor(Color.rgb(15,23,42));
  webView = new WebView(this);
  webView.setBackgroundColor(Color.rgb(15,23,42));
  webView.getSettings().setJavaScriptEnabled(true);
  webView.setWebViewClient(new WebViewClient());
  setContentView(webView);
  webView.loadUrl("file:///android_asset/index.html");
 }
 @Override public void onBackPressed() {
  if (webView != null && webView.canGoBack()) webView.goBack(); else super.onBackPressed();
 }
}
