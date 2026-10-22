package com.ziokt.effort;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.net.*;
import android.os.*;
import java.util.ArrayList;
import java.util.concurrent.*;
import java.util.function.Consumer;

public final class EffortService extends Service {
    public static final String START="com.ziokt.effort.START",STOP="com.ziokt.effort.STOP";
    static final String CHANNEL="effort";
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private final ArrayList<Consumer<String>> observers=new ArrayList<>();
    private ConnectivityManager manager;private Network current;private boolean online,wanted,foreground;
    private Work work;private Future<?> future;private String status="尚未启动";private long lastProgress;
    public final class LocalBinder extends Binder { public EffortService service(){return EffortService.this;} }
    public void watch(Consumer<String> observer){observers.add(observer);observer.accept(status);}
    public void unwatch(Consumer<String> observer){observers.remove(observer);}
    @Override public IBinder onBind(Intent intent){return new LocalBinder();}
    private final ConnectivityManager.NetworkCallback callback=new ConnectivityManager.NetworkCallback(){
        @Override public void onAvailable(Network network){current=network;}
        @Override public void onCapabilitiesChanged(Network network,NetworkCapabilities caps){
            if(network.equals(current))networkChanged(caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)&&caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED));
        }
        @Override public void onLost(Network network){if(network.equals(current)){current=null;networkChanged(false);}}
    };
    @Override public void onCreate(){
        super.onCreate();NotificationManager notifications=getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CHANNEL,"Ziokt 助力状态与停止",NotificationManager.IMPORTANCE_LOW));
        manager=getSystemService(ConnectivityManager.class);manager.registerDefaultNetworkCallback(callback,handler);
        // One initial snapshot; future changes arrive through system callbacks, never probes.
        current=manager.getActiveNetwork();NetworkCapabilities caps=current==null?null:manager.getNetworkCapabilities(current);
        online=caps!=null&&caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)&&caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
    }
    private void networkChanged(boolean value){
        if(online==value)return;online=value;
        if(!online){cancel();if(wanted)status("网络已断开，已暂停；等待系统网络恢复");}
        else if(wanted){status("网络已恢复，继续先前助力");launch();}
    }
    @Override public int onStartCommand(Intent intent,int flags,int id){
        if(intent!=null&&STOP.equals(intent.getAction())){wanted=false;getSharedPreferences("effort",0).edit().putBoolean("wanted",false).apply();cancel();status("已停止；不会自动恢复");stopForeground(STOP_FOREGROUND_REMOVE);foreground=false;stopSelf();return START_NOT_STICKY;}
        wanted=getSharedPreferences("effort",0).getBoolean("wanted",false);
        if(!wanted){stopSelf();return START_NOT_STICKY;}
        foreground=true;String mode=getSharedPreferences("effort",0).getString("mode","network");
        if(Build.VERSION.SDK_INT>=34)startForeground(1,notification(),"compute".equals(mode)?ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE:ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        else startForeground(1,notification());
        cancel();if(online)launch();else status("网络已断开，已暂停；等待系统网络恢复");return START_STICKY;
    }
    private Notification notification(){
        PendingIntent open=PendingIntent.getActivity(this,1,new Intent(this,MainActivity.class),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop=PendingIntent.getService(this,2,new Intent(this,EffortService.class).setAction(STOP),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_menu_share).setContentTitle("Ziokt 助力 · 可随时停止").setContentText(status).setStyle(new Notification.BigTextStyle().bigText(status)).setContentIntent(open).setOngoing(true).addAction(new Notification.Action.Builder(android.R.drawable.ic_media_pause,"停止助力",stop).build()).build();
    }
    private void status(String value){status=value;for(Consumer<String> observer:new ArrayList<>(observers))observer.accept(value);if(foreground)getSystemService(NotificationManager.class).notify(1,notification());}
    private void cancel(){if(work!=null)work.cancel();work=null;if(future!=null)future.cancel(true);future=null;}
    private void launch(){
        if(!wanted||!online||work!=null)return;
        final Work[] reference=new Work[1];Work task=new Work(value->handler.post(()->{if(work!=reference[0])return;long now=SystemClock.elapsedRealtime();if(value.contains("字节")&&now-lastProgress<1500)return;lastProgress=now;status(value);}));reference[0]=task;work=task;
        String mode=getSharedPreferences("effort",0).getString("mode","network");int level=getSharedPreferences("effort",0).getInt("level",1);
        future=executor.submit(()->{
            while(!task.cancelled){
                try{if("compute".equals(mode))task.compute(level);else task.network();}
                catch(CancellationException|InterruptedException stopped){return;}
                catch(Exception error){handler.post(()->{if(work==task)status("业务暂不可用，稍后重试；不是已结算贡献");});try{task.pause(10000);}catch(InterruptedException|CancellationException stopped){return;}}
            }
        });
    }
    @Override public void onDestroy(){wanted=false;cancel();manager.unregisterNetworkCallback(callback);executor.shutdownNow();observers.clear();super.onDestroy();}
}
