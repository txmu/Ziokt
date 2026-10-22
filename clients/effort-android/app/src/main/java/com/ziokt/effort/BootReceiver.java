package com.ziokt.effort;
import android.app.*;
import android.content.*;

public final class BootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context,Intent intent){
        if(!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction()))return;
        android.content.SharedPreferences prefs=context.getSharedPreferences("effort",0);
        if(!prefs.getBoolean("boot",false)||!prefs.getBoolean("wanted",false))return;
        try{context.startForegroundService(new Intent(context,EffortService.class).setAction(EffortService.START));}
        catch(RuntimeException blocked){
            NotificationManager manager=context.getSystemService(NotificationManager.class);manager.createNotificationChannel(new NotificationChannel(EffortService.CHANNEL,"Ziokt 助力",NotificationManager.IMPORTANCE_LOW));
            PendingIntent open=PendingIntent.getActivity(context,1,new Intent(context,MainActivity.class),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
            try{manager.notify(2,new Notification.Builder(context,EffortService.CHANNEL).setSmallIcon(android.R.drawable.ic_menu_share).setContentTitle("系统限制开机恢复").setContentText("请打开 Ziokt 助力后主动启用。").setContentIntent(open).setAutoCancel(true).build());}catch(SecurityException ignored){}
        }
    }
}
