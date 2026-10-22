package com.ziokt.effort;
import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.*;
import android.view.*;
import android.widget.*;
import java.util.function.Consumer;

/** Native controls only: no WebView, browser runtime, native libraries or background polling UI. */
public final class MainActivity extends Activity {
    private SharedPreferences prefs;private Spinner mode,level;private CheckBox boot;private TextView status;
    private EffortService service;private boolean bound;
    private final Consumer<String> observer=value->status.setText(value);
    private final ServiceConnection connection=new ServiceConnection(){
        public void onServiceConnected(ComponentName name,IBinder binder){service=((EffortService.LocalBinder)binder).service();service.watch(observer);}
        public void onServiceDisconnected(ComponentName name){service=null;}
    };
    private TextView text(String value,int size){TextView v=new TextView(this);v.setText(value);v.setTextSize(size);v.setPadding(0,12,0,12);return v;}
    @Override public void onCreate(Bundle state){
        super.onCreate(state);prefs=getSharedPreferences("effort",0);
        ScrollView scroll=new ScrollView(this);LinearLayout layout=new LinearLayout(this);layout.setOrientation(LinearLayout.VERTICAL);int pad=(int)(20*getResources().getDisplayMetrics().density);layout.setPadding(pad,pad,pad,pad);scroll.addView(layout);setContentView(scroll);
        layout.addView(text("Ziokt 轻量助力",26));layout.addView(text("单线程、有限缓冲。会使用流量和电量；贡献归节点，不保证收益。",16));
        mode=new Spinner(this);mode.setContentDescription("助力方式");mode.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,new String[]{"轻量网络协作（主网直连，非匿名）","计算协作（单线程）"}));mode.setSelection("compute".equals(prefs.getString("mode","network"))?1:0);layout.addView(mode);
        level=new Spinner(this);level.setContentDescription("计算档位");level.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,new String[]{"1 · 最低占用（默认）","2 · 安静","3 · 均衡","4 · 积极","5 · 高强度（仍为单线程）"}));level.setSelection(Math.max(0,Math.min(4,prefs.getInt("level",1)-1)));layout.addView(level);
        boot=new CheckBox(this);boot.setText("允许开机后恢复上次助力（可随时取消）");boot.setChecked(prefs.getBoolean("boot",false));boot.setOnCheckedChangeListener((b,value)->prefs.edit().putBoolean("boot",value).apply());layout.addView(boot);
        Button start=new Button(this);start.setText("一键启用（后台常驻通知）");start.setOnClickListener(v->{if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},1);return;}startWork();});layout.addView(start);
        Button stop=new Button(this);stop.setText("停止助力");stop.setOnClickListener(v->stopWork());layout.addView(stop);
        status=text("尚未启动",18);status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);layout.addView(status);
        layout.addView(text("断网暂停，联网恢复；手动停止后不自动恢复。仅接收系统网络回调，不反复检测网络。后台运行受系统和厂商省电策略约束。",15));
        Button website=new Button(this);website.setText("打开奋斗页与贡献记录");website.setOnClickListener(v->startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(Work.ORIGIN+"/"))));layout.addView(website);
        layout.addView(text("Android 9+ · Java 通用 APK · ARM 32/64 位\n源码："+BuildConfig.SOURCE_SHA,12));
    }
    private void startWork(){prefs.edit().putString("mode",mode.getSelectedItemPosition()==1?"compute":"network").putInt("level",level.getSelectedItemPosition()+1).putBoolean("wanted",true).apply();try{startForegroundService(new Intent(this,EffortService.class).setAction(EffortService.START));}catch(RuntimeException failure){prefs.edit().putBoolean("wanted",false).apply();status.setText("系统未批准后台运行，请在前台重试");}}
    private void stopWork(){prefs.edit().putBoolean("wanted",false).apply();startService(new Intent(this,EffortService.class).setAction(EffortService.STOP));status.setText("已停止；不会自动恢复");}
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] grants){super.onRequestPermissionsResult(request,permissions,grants);if(request==1&&grants.length>0&&grants[0]==PackageManager.PERMISSION_GRANTED)startWork();else status.setText("请允许状态通知后启用，以便随时停止。");}
    @Override protected void onStart(){super.onStart();bound=bindService(new Intent(this,EffortService.class),connection,BIND_AUTO_CREATE);}
    @Override protected void onStop(){if(service!=null)service.unwatch(observer);service=null;if(bound){unbindService(connection);bound=false;}super.onStop();}
}
