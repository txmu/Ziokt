package com.ziokt.effort;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.CancellationException;
import java.util.function.Consumer;
import javax.net.ssl.HttpsURLConnection;
import org.json.*;

/** One bounded native worker. No browser engine, JNI, connectivity probes or arbitrary destinations. */
final class Work {
    static final String ORIGIN="https://fendou.ziokt.com";
    private final String origin;
    private String expectedNetwork;private boolean networkConfigLoaded;
    private final Consumer<JSONObject> receiptSink;
    static boolean validOrigin(String value){try{java.net.URI uri=new java.net.URI(value);return "https".equals(uri.getScheme())&&uri.getHost()!=null&&uri.getUserInfo()==null&&(uri.getRawPath()==null||uri.getRawPath().isEmpty()||uri.getRawPath().equals("/"))&&uri.getRawQuery()==null&&uri.getRawFragment()==null;}catch(Exception error){return false;}}
    volatile boolean cancelled;
    private volatile HttpsURLConnection request;
    private final Consumer<String> status;
    Work(Consumer<String> status) { this(status,ORIGIN); }
    Work(Consumer<String> status,String origin) { this(status,origin,value->{}); }
    Work(Consumer<String> status,String origin,Consumer<JSONObject> receiptSink) { this.receiptSink=receiptSink;if(!validOrigin(origin))throw new IllegalArgumentException("HTTPS node origin required");this.status=status;this.origin=origin.endsWith("/")?origin.substring(0,origin.length()-1):origin; }
    void cancel() { cancelled=true; HttpsURLConnection c=request;if(c!=null)c.disconnect(); }
    void check() { if(cancelled||Thread.currentThread().isInterrupted())throw new CancellationException(); }
    void pause(long ms) throws InterruptedException { check();Thread.sleep(ms);check(); }
    JSONObject post(String path,JSONObject value,String token) throws Exception {
        check();if(!path.matches("/api/(job|proof|people/config|people/direct/(open|[ab]/(read|write|ack|close)))"))throw new IOException("INVALID_ENDPOINT");
        byte[] body=value.toString().getBytes(StandardCharsets.UTF_8);if(body.length>8192)throw new IOException("REQUEST_LIMIT");
        HttpsURLConnection c=(HttpsURLConnection)new URL(origin+path).openConnection();request=c;
        c.setInstanceFollowRedirects(false);c.setConnectTimeout(15000);c.setReadTimeout(15000);c.setUseCaches(false);boolean config=path.equals("/api/people/config");c.setRequestMethod(config?"GET":"POST");if(!config){c.setDoOutput(true);c.setFixedLengthStreamingMode(body.length);}
        c.setRequestProperty("Content-Type","application/json");c.setRequestProperty("Origin",origin);
        if(token!=null)c.setRequestProperty("Authorization","Bearer "+token);
        try {
            check();if(!config){try(OutputStream out=c.getOutputStream()){out.write(body);}}
            int code=c.getResponseCode();InputStream input=code==200?c.getInputStream():c.getErrorStream();
            if(input==null)throw new IOException("HTTP_"+code);
            ByteArrayOutputStream bytes=new ByteArrayOutputStream(8192);byte[] buffer=new byte[2048];int count;
            try(InputStream in=input){while((count=in.read(buffer))!=-1){check();if(bytes.size()+count>32768)throw new IOException("RESPONSE_LIMIT");bytes.write(buffer,0,count);}}
            JSONObject result=new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8));
            if(code!=200||result.has("error"))throw new IOException("HTTP_"+code);
            return result;
        } finally { c.disconnect();if(request==c)request=null; }
    }
    static JSONObject object(Object... values) throws JSONException {
        JSONObject result=new JSONObject();for(int i=0;i<values.length;i+=2)result.put((String)values[i],values[i+1]);return result;
    }
    static String hash(String value) throws Exception {
        byte[] bytes=MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));StringBuilder s=new StringBuilder(64);
        for(byte b:bytes)s.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return s.toString();
    }
    String networkId(String observed) throws Exception {
        if(!networkConfigLoaded){JSONObject config=post("/api/people/config",object(),null);if(!"ziokt.people-help.v1".equals(config.getString("schema")))throw new IOException("INVALID_NETWORK_CONFIG");if(config.has("network_id")&&!config.isNull("network_id"))expectedNetwork=config.getString("network_id");networkConfigLoaded=true;}
        if(expectedNetwork==null)expectedNetwork=observed;
        if(expectedNetwork!=null&&!expectedNetwork.matches("[A-Za-z0-9_-]{1,64}"))throw new IOException("INVALID_NETWORK_CONFIG");
        return expectedNetwork;
    }
    void compute(int level) throws Exception {
        JSONObject job=post("/api/job",object(),null);
        if(!job.getBoolean("available")){status.accept("等待真实计算任务，不进行无效计算");pause(5000);return;}
        String network=job.getString("network_id"),submitter=job.getString("submitter_id"),problem=job.getString("problem_id"),token=job.getString("token"),start=job.getString("start");
        String expected=networkId(network);
        long expires=job.getLong("expires"),limit=job.getLong("limit");
        if(!network.equals(expected)||!job.getString("engine_id").equals("corium/internal-engine-zero-v1")||job.getInt("difficulty")!=3||!submitter.matches("[a-f0-9]{64}")||!problem.matches("[a-f0-9]{64}")||!token.matches("[a-f0-9]{48}")||!start.matches("[0-9]{1,18}")||limit<1||limit>1000000||expires>System.currentTimeMillis()/1000+120)throw new IOException("INVALID_JOB");
        long base=Long.parseLong(start);if(base>Long.MAX_VALUE-limit)throw new IOException("NONCE_LIMIT");
        MessageDigest digest=MessageDigest.getInstance("SHA-256");int[] batches={8,16,32,64,128};int[] delays={100,80,60,40,20};int selected=Math.max(0,Math.min(4,level-1));
        status.accept("计算协作运行中 · 单线程 · 档位 "+(selected+1));
        for(long offset=0;offset<limit&&System.currentTimeMillis()/1000<expires;offset++) {
            check();String nonce=Long.toString(base+offset);byte[] raw=digest.digest((network+submitter+nonce+problem).getBytes(StandardCharsets.UTF_8));
            if(raw[0]==0&&(raw[1]&240)==0){JSONObject receipt=post("/api/proof",object("token",token,"nonce",nonce),null);if(!receipt.optBoolean("accepted",false))throw new IOException("PROOF_UNCONFIRMED");status.accept("证明已提交，等待原生共识；不保证奖励");pause(5000);return;}
            if(offset%batches[selected]==batches[selected]-1)pause(delays[selected]);
        }
    }
    JSONObject relay(String side,String op,JSONObject args,String token) throws Exception {
        JSONObject wire=object("arguments",args,"padding","");
        if(op.equals("write")){int n=6144-wire.toString().length();if(n>0){char[] padding=new char[n];java.util.Arrays.fill(padding,'0');wire.put("padding",new String(padding));}}
        return post("/api/people/direct/"+side+"/"+op,wire,token);
    }
    void network() throws Exception {
        JSONObject opened=post("/api/people/direct/open",object(),null);
        if(opened.getString("state").equals("waiting")){status.accept("节点直连已启用 · 等待真实转发任务（非匿名）");pause(5000);return;}
        String token=opened.getString("session");
        if(!opened.getString("state").equals("open")||!opened.getString("network_id").equals(networkId(opened.getString("network_id")))||!token.matches("[A-Za-z0-9_-]{40,64}"))throw new IOException("INVALID_SESSION");
        boolean[] fin={false,false};long total=0;long began=android.os.SystemClock.elapsedRealtime();String[] sides={"a","b"};
        while(!(fin[0]&&fin[1])) {
            check();if(total>8*1024*1024L||android.os.SystemClock.elapsedRealtime()-began>300000)throw new IOException("LOCAL_RELAY_BUDGET");boolean moved=false;
            for(int index=0;index<2;index++) {
                if(fin[index])continue;String from=sides[index],to=sides[1-index];JSONObject response=relay(from,"read",object("session",from),token);
                String state=response.getString("state");if(state.equals("idle"))continue;
                if(!state.equals("frame"))throw new IOException("INVALID_FRAME");JSONObject frame=response.getJSONObject("frame");String kind=frame.getString("kind"),encoded=frame.getString("data");long sequence=frame.getLong("sequence");
                if(sequence<0||sequence>=4294967296L||encoded.length()>5464||!(kind.equals("data")||kind.equals("fin")))throw new IOException("FRAME_LIMIT");
                byte[] bytes=android.util.Base64.decode(encoded,android.util.Base64.NO_WRAP);
                if(bytes.length>4096||!android.util.Base64.encodeToString(bytes,android.util.Base64.NO_WRAP).equals(encoded)||kind.equals("fin")!=(bytes.length==0))throw new IOException("INVALID_FRAME");
                JSONObject receipt=relay(to,"write",object("session",to,"frame",frame),token);if(!receipt.getString("state").equals("native_written"))throw new IOException("WRITE_UNCONFIRMED");
                JSONObject ack=relay(from,"ack",object("session",from,"sequence",sequence),token);if(!ack.getString("state").equals("acknowledged"))throw new IOException("ACK_UNCONFIRMED");if(ack.has("reputation_receipt"))receiptSink.accept(ack.getJSONObject("reputation_receipt"));
                moved=true;if(kind.equals("fin"))fin[index]=true;else total+=bytes.length;
            }
            if(moved)status.accept("主网直连已转发 "+total+" 字节 · 非匿名，尚未结算贡献");pause(500);
        }
        relay("a","close",object("session","a"),token);
    }
}
